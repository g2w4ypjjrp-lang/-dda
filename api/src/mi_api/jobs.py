"""Zamanlanmış işlerin gövdeleri — Celery işçisi (``mi_api.worker``) ve tek sunucu zamanlayıcısı
(``mi_api.scheduler``) aynı fonksiyonları çalıştırır."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis

from mi_api.config import Settings
from mi_api.db import Database
from mi_api.football.runtime import FootballRuntime
from mi_api.football.sync import Job, Trigger


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


async def settle_coupons() -> dict[str, int]:
    from mi_api.coupons.api import settle_coupons as settle

    settings = Settings()
    db = Database(settings.database_url.get_secret_value(), pool_size=1)
    try:
        async with db.session() as session:
            return await settle(session, datetime.now(UTC))
    finally:
        await db.close()


async def scan_notifications() -> dict[str, int]:
    from mi_api.engage.scan import scan

    settings = Settings()
    db = Database(settings.database_url.get_secret_value(), pool_size=1)
    try:
        async with db.session() as session:
            return await scan(session, datetime.now(UTC))
    finally:
        await db.close()


async def daily_backup(settings: Settings) -> dict[str, Any]:
    """Günlük yedek + geri yükleme doğrulaması. MI_BACKUP_DIR yoksa atlanır (Action Center
    uyarır)."""
    from mi_api.ops import backup

    if not settings.backup_dir:
        return {"status": "skipped", "reason": "MI_BACKUP_DIR yok"}
    out = await backup.create(settings, "schedule")
    return {"id": out.id, "status": out.status, "verify_ok": out.detail.get("verify", {}).get("ok")}
