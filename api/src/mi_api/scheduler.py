# ruff: noqa: E501
"""Tek sunucu zamanlayıcısı (``MI_SINGLE_SERVER=true``; Windows hafif kurulum, deploy/windows).

Redis ve Celery olmadan, API sürecinin içinde, Celery Beat ile aynı programı çalıştırır:
kupon sonuçlandırma, bildirim taraması, günlük yedek ve (veri sağlayıcı varsa) futbol verisi
işleri. Bir iş bitmeden aynı iş yeniden başlamaz; hata zamanlayıcıyı durdurmaz (günlüğe yazılır).
API yalnızca **tek süreçle** çalıştırılmalıdır (hız sınırı da bellekte tutulur).

Kalp atışı (``last_beat``) Sistem Sağlığı ve Action Center'da "işçi/zamanlayıcı" olarak görünür.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any

from mi_api import aio, jobs
from mi_api.config import Settings

log = logging.getLogger("mi_api.scheduler")
TICK_S = 5.0


@dataclass
class Job:
    name: str
    run: Callable[[], Awaitable[Any]]
    every: timedelta | None = None
    daily_at: time | None = None  # UTC
    last_run: datetime | None = None
    running: bool = False

    def due(self, now: datetime) -> bool:
        if self.running:
            return False
        if self.every is not None:
            return self.last_run is None or now - self.last_run >= self.every
        if self.daily_at is None:
            return False
        slot = datetime.combine(now.date(), self.daily_at, tzinfo=UTC)
        return now >= slot and (self.last_run is None or self.last_run < slot)


def _football(job: str, params: dict[str, Any]) -> Callable[[], Awaitable[Any]]:
    return lambda: jobs.run_job(job, dict(params))  # type: ignore[arg-type]


def build_jobs(settings: Settings) -> list[Job]:
    """Celery Beat programının (mi_api.worker) tek süreç karşılığı."""
    out = [
        Job("coupons-settle", jobs.settle_coupons, every=timedelta(seconds=900)),
        Job("notifications-scan", jobs.scan_notifications, every=timedelta(seconds=300)),
        # pg_dump/pg_restore engelleyici: ayrı iş parçacığında, kendi olay döngüsüyle.
        Job(
            "backup-daily",
            lambda: asyncio.to_thread(aio.run, jobs.daily_backup(settings)),
            daily_at=time(3, 17),
        ),
    ]
    if settings.football_provider != "none":
        out += [
            Job("fixtures-today", _football("fixtures_date", {"offset_days": 0}), every=timedelta(seconds=600)),
            Job("fixtures-tomorrow", _football("fixtures_date", {"offset_days": 1}), every=timedelta(hours=1)),
            Job("fixtures-yesterday", _football("fixtures_date", {"offset_days": -1}), every=timedelta(hours=1)),
            Job("live", _football("live", {}), every=timedelta(seconds=60)),
            Job("upcoming-details", _football("upcoming_details", {}), every=timedelta(seconds=900)),
            Job("standings", _football("standings_active", {}), every=timedelta(hours=6)),
        ]  # fmt: skip
    return out


@dataclass
class Scheduler:
    settings: Settings
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    jobs: list[Job] = field(default_factory=list)
    last_beat: datetime | None = None
    _tasks: set[asyncio.Task[None]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.jobs:
            self.jobs = build_jobs(self.settings)

    async def _run(self, job: Job) -> None:
        try:
            result = await job.run()
            log.info(
                "zamanlanmış iş tamam",
                extra={"fields": {"job": job.name, "result": str(result)[:300]}},
            )
        except Exception:
            log.exception("zamanlanmış iş başarısız", extra={"fields": {"job": job.name}})
        finally:
            job.running = False

    def tick(self) -> list[str]:
        """Zamanı gelen işleri başlatır; başlatılanların adlarını döner."""
        now = self.clock()
        self.last_beat = now
        started = []
        for job in self.jobs:
            if job.due(now):
                job.running = True
                job.last_run = now
                task = asyncio.create_task(self._run(job))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                started.append(job.name)
        return started

    async def run_forever(self) -> None:
        log.info(
            "tek sunucu zamanlayıcısı başladı",
            extra={"fields": {"jobs": [j.name for j in self.jobs]}},
        )
        while True:
            self.tick()
            await asyncio.sleep(TICK_S)

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
