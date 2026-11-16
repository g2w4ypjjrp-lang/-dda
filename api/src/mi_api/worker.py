"""Celery işçisi ve zamanlanmış futbol verisi işleri (Celery Beat).

Çalıştırma::

    celery -A mi_api.worker worker --loglevel=INFO --concurrency=2
    celery -A mi_api.worker beat --loglevel=INFO

Program, verinin türüne göre yenileme sıklığını ayarlar. Her iş kota bütçesinden geçer;
bütçe dolarsa düşük öncelikli işler atlanır (``football_sync_runs``'ta "skipped" görünür).
Aynı iş aynı anda iki kez çalışmaz (Redis kilidi).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import Celery, signals
from redis import Redis as SyncRedis
from redis.asyncio import Redis

from mi_api.config import Settings
from mi_api.db import Database
from mi_api.football.runtime import FootballRuntime
from mi_api.football.sync import Job, Trigger
from mi_api.logs import configure_logging

_settings = Settings()
_broker = _settings.redis_url.get_secret_value() if _settings.redis_url else "memory://"

app = Celery("mi", broker=_broker)
app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Bugün ve yarının fikstürü (UTC günleri; Türkiye günü iki UTC gününe yayılır).
        "fixtures-today": {
            "task": "mi.football.sync",
            "schedule": 600.0,
            "args": ("fixtures_date", {"offset_days": 0}),
        },
        "fixtures-tomorrow": {
            "task": "mi.football.sync",
            "schedule": 3600.0,
            "args": ("fixtures_date", {"offset_days": 1}),
        },
        "fixtures-yesterday": {
            "task": "mi.football.sync",
            "schedule": 3600.0,
            "args": ("fixtures_date", {"offset_days": -1}),
        },
        # Canlı: veritabanında canlı/başlamak üzere maç yoksa istek atmadan atlanır.
        "live": {"task": "mi.football.sync", "schedule": 60.0, "args": ("live", {})},
        "upcoming-details": {
            "task": "mi.football.sync",
            "schedule": 900.0,
            "args": ("upcoming_details", {}),
        },
        "standings": {
            "task": "mi.football.sync",
            "schedule": 6 * 3600.0,
            "args": ("standings_active", {}),
        },
    },
)


@signals.setup_logging.connect  # type: ignore[untyped-decorator]
def _setup_logging(**_: Any) -> None:
    """Celery kendi log ayarını yapmasın; uygulamanın JSON + maskeleme ayarı kullanılsın."""
    configure_logging(_settings.log_level, json_output=_settings.log_json)


async def run_job(
    job: Job, params: dict[str, Any], trigger: Trigger = "schedule"
) -> dict[str, Any]:
    settings = Settings()
    redis = Redis.from_url(settings.redis_url.get_secret_value()) if settings.redis_url else None
    db = Database(settings.database_url.get_secret_value(), pool_size=2)

    def clock() -> datetime:
        return datetime.now(UTC)

    runtime = FootballRuntime(settings, clock=clock, redis=redis)
    service, provider = runtime.service(db)
    try:
        if "offset_days" in params:
            day = (clock() + timedelta(days=int(params.pop("offset_days")))).date()
            params = {**params, "date": day.isoformat()}
        result = await service.run(job, params, trigger=trigger)
        return result.as_dict()
    finally:
        if provider is not None:
            await provider.aclose()
        await db.close()
        if redis is not None:
            await redis.aclose()


@app.task(name="mi.football.sync")  # type: ignore[untyped-decorator]
def football_sync(job: Job, params: dict[str, Any]) -> dict[str, Any]:
    lock_key = f"mi:lock:football:{job}:{sorted(params.items())}"
    redis = SyncRedis.from_url(_broker) if _settings.redis_url else None
    lock = redis.lock(lock_key, timeout=900, blocking=False) if redis else None
    if lock is not None and not lock.acquire(blocking=False):
        return {"job": job, "status": "skipped", "message": "Aynı iş zaten çalışıyor"}
    try:
        return asyncio.run(run_job(job, dict(params)))
    finally:
        if lock is not None:
            lock.release()
