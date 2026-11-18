"""Tek sunucu modu (Windows hafif kurulum): Redis/Celery yok, işler API içinde zamanlanır."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, time, timedelta
from typing import Any

import psycopg
import pytest
from pydantic import ValidationError

from conftest import Clock, make_staff, use
from mi_api import aio
from mi_api.config import Settings
from mi_api.scheduler import Job, Scheduler, build_jobs

KEK = base64.b64encode(b"k" * 32).decode()
PROD: dict[str, Any] = {
    "environment": "production",
    "secret_kek": KEK,
    "web_origins": ["https://futbol.canarslan.net.tr"],
    "admin_origins": ["https://futbol.canarslan.net.tr"],
    "public_web_url": "https://futbol.canarslan.net.tr",
}


def test_single_server_settings() -> None:
    ok = Settings(
        database_url="postgresql://futbol:p@127.0.0.1:5433/futbol",
        single_server=True,
        database_private_network=True,
        **PROD,
    )
    assert ok.redis_url is None and ok.single_server
    # Tek sunucu modu olmadan Redis zorunlu; aynı makinedeki veritabanı yalnızca açık beyanla.
    with pytest.raises(ValidationError, match="MI_REDIS_URL"):
        Settings(database_url="postgresql://f:p@127.0.0.1/f", database_private_network=True, **PROD)
    with pytest.raises(ValidationError, match="verify-full"):
        Settings(database_url="postgresql://f:p@127.0.0.1/f", single_server=True, **PROD)
    with pytest.raises(ValidationError, match="aynı makinedeki"):
        Settings(
            database_url="postgresql://f:p@db.example.com/f",
            single_server=True,
            database_private_network=True,
            **PROD,
        )


def test_job_due_rules() -> None:
    async def noop() -> None:
        return None

    now = datetime(2026, 11, 18, 3, 16, tzinfo=UTC)
    every = Job("x", noop, every=timedelta(minutes=5))
    assert every.due(now)
    every.last_run = now
    assert not every.due(now + timedelta(minutes=4)) and every.due(now + timedelta(minutes=5))
    every.running = True
    assert not every.due(now + timedelta(hours=1))  # aynı iş üst üste binmez

    daily = Job("d", noop, daily_at=time(3, 17))
    assert not daily.due(now)  # 03:17'den önce
    assert daily.due(now + timedelta(minutes=1))
    daily.last_run = now + timedelta(minutes=1)
    assert not daily.due(now + timedelta(hours=5))  # aynı gün ikinci kez yok
    assert daily.due(now + timedelta(days=1, minutes=1))


def test_schedule_mirrors_celery_beat(monkeypatch: Any) -> None:
    """Tek sunucu programı, Celery Beat programıyla aynı işleri içerir (kalp atışı hariç)."""
    monkeypatch.setenv("MI_DATABASE_URL", "postgresql://x/y")
    from mi_api.worker import app as celery_app

    beat = set(celery_app.conf.beat_schedule) - {"heartbeat"}
    with_provider = Settings(
        database_url="postgresql://x/y", football_provider="football_data", football_api_key="k"
    )
    assert {j.name for j in build_jobs(with_provider)} == beat
    no_provider = {j.name for j in build_jobs(Settings(database_url="postgresql://x/y"))}
    assert no_provider == {"coupons-settle", "notifications-scan", "backup-daily"}


async def test_scheduler_runs_jobs_without_overlap() -> None:
    calls: list[str] = []
    gate = asyncio.Event()

    async def slow() -> None:
        calls.append("slow")
        await gate.wait()

    async def boom() -> None:
        calls.append("boom")
        raise RuntimeError("bozuk iş")

    t = [datetime(2026, 11, 18, 12, 0, tzinfo=UTC)]
    s = Scheduler(
        Settings(database_url="postgresql://x/y"),
        clock=lambda: t[0],
        jobs=[
            Job("slow", slow, every=timedelta(seconds=1)),
            Job("boom", boom, every=timedelta(seconds=1)),
        ],
    )
    assert sorted(s.tick()) == ["boom", "slow"]
    await asyncio.sleep(0)
    t[0] += timedelta(seconds=5)
    # "slow" hâlâ çalışıyor → yeniden başlamaz; hata veren iş zamanlayıcıyı durdurmaz.
    assert s.tick() == ["boom"]
    assert s.last_beat == t[0]
    gate.set()
    await asyncio.sleep(0.01)
    await s.stop()
    assert calls.count("slow") == 1 and calls.count("boom") == 2


async def test_real_jobs_run_against_database(dsn: str, monkeypatch: Any) -> None:
    monkeypatch.setenv("MI_DATABASE_URL", dsn)
    s = Scheduler(Settings(database_url=dsn, single_server=True))
    for job in s.jobs:
        if job.name in ("coupons-settle", "notifications-scan"):
            result = await job.run()
            assert isinstance(result, dict)
    # Yedek dizini yoksa atlanır (Action Center ayrıca uyarır).
    backup = next(j for j in s.jobs if j.name == "backup-daily")
    assert (await backup.run())["status"] == "skipped"


async def test_health_and_action_center_use_in_process_heartbeat(
    app_factory: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    app = app_factory(single_server=True)
    scheduler = app.state.scheduler
    assert isinstance(scheduler, Scheduler)
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with use(admin.client) as a:
        keys = {i["key"] for i in (await a.get("/admin/v1/actions")).json()["items"]}
        assert "worker:heartbeat" in keys  # hiç atış yok → uyarı
        scheduler.last_beat = datetime.now(UTC)
        h = (await a.get("/admin/v1/health")).json()["components"]
        assert h["redis"]["status"] == "not_used" and h["queue"]["status"] == "not_used"
        assert h["workers"]["status"] == "ok" and h["scheduler"]["status"] == "ok"
        # Uygulama saati (testte sabit) ile karşılaştırılır: atışı o ana çek.
        scheduler.last_beat = clock()
        keys = {i["key"] for i in (await a.get("/admin/v1/actions")).json()["items"]}
        assert "worker:heartbeat" not in keys
        scheduler.last_beat = clock() - timedelta(minutes=10)
        items = {i["key"]: i for i in (await a.get("/admin/v1/actions")).json()["items"]}
        assert items["worker:heartbeat"]["severity"] == "critical"
    # Normal kurulumda (tek sunucu kapalı) zamanlayıcı yok.
    assert app_factory().state.scheduler is None


def test_aio_run_uses_selector_loop_on_windows(monkeypatch: Any) -> None:
    async def kind() -> type:
        return type(asyncio.get_running_loop())

    monkeypatch.setattr(aio, "WINDOWS", True)
    assert issubclass(aio.run(kind()), asyncio.SelectorEventLoop)
