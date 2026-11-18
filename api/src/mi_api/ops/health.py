"""System Health: bileşenlerin gerçek durum ölçümleri.

Her bileşen ``{"status": "ok" | "degraded" | "down" | "not_configured" | "unknown", ...}`` döner.
Ölçülemeyen değer uydurulmaz: ``None`` ve nedeni yazılır (ör. Redis yoksa kuyruk uzunluğu).
CPU/RAM/disk bu API sürecinin çalıştığı makineye aittir (Linux ``/proc``); başka sunucuların
(işçi, veritabanı) kaynakları için harici izleme gerekir (Faz 10).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.config import Settings
from mi_api.football.models import SyncRun
from mi_api.migrate import current_revision, head_revision
from mi_api.ops.metrics import Metrics

HEARTBEAT_KEY = "mi:heartbeat:worker"
HEARTBEAT_STALE = timedelta(minutes=5)


def _meminfo() -> dict[str, Any] | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            rows = {line.split(":")[0]: int(line.split()[1]) for line in f if ":" in line}
        total, avail = rows["MemTotal"] * 1024, rows["MemAvailable"] * 1024
        return {"total_bytes": total, "used_pct": round((1 - avail / total) * 100, 1)}
    except (OSError, KeyError, ValueError):
        return None


def host_resources() -> dict[str, Any]:
    load = os.getloadavg() if hasattr(os, "getloadavg") else None
    cpus = os.cpu_count() or 1
    disk = shutil.disk_usage("/")
    return {
        "scope": "API süreci makinesi",
        "cpu": {
            "cores": cpus,
            "load_1m": round(load[0], 2),
            "load_pct": round(load[0] / cpus * 100, 1),
        }
        if load
        else None,
        "memory": _meminfo(),
        "disk": {"total_bytes": disk.total, "used_pct": round(disk.used / disk.total * 100, 1)},
    }


async def snapshot(
    db: AsyncSession,
    settings: Settings,
    redis: Redis | None,
    metrics: Metrics,
    now: datetime,
    local_heartbeat: datetime | None = None,
) -> dict[str, Any]:
    """``local_heartbeat``: tek sunucu modunda API içindeki zamanlayıcının son atışı."""
    comp: dict[str, Any] = {}

    t0 = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - t0) * 1000, 1)
        current = await asyncio.to_thread(
            current_revision, settings.database_url.get_secret_value()
        )
        head = head_revision()
        comp["database"] = {
            "status": "ok" if current == head else "degraded",
            "latency_ms": latency,
            "schema": current,
            "schema_head": head,
        }
    except Exception as exc:
        comp["database"] = {"status": "down", "error": type(exc).__name__}

    heartbeat: datetime | None = None
    if redis is None and settings.single_server:
        comp["redis"] = {"status": "not_used", "detail": "Tek sunucu modu: Redis kullanılmıyor"}
        comp["queue"] = {"status": "not_used", "detail": "İşler API sürecinin içinde çalışır"}
        heartbeat = local_heartbeat
    elif redis is None:
        comp["redis"] = {"status": "not_configured"}
        comp["queue"] = {"status": "unknown", "detail": "Redis yok; kuyruk ölçülemez"}
    else:
        try:
            t0 = time.perf_counter()
            await redis.ping()
            comp["redis"] = {
                "status": "ok",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
            depth = int(await redis.llen("celery")) + int(await redis.llen("ml"))
            comp["queue"] = {"status": "ok" if depth < 100 else "degraded", "depth": depth}
            raw = await redis.get(HEARTBEAT_KEY)
            heartbeat = (
                datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw)
                if raw
                else None
            )
        except Exception as exc:
            comp["redis"] = {"status": "down", "error": type(exc).__name__}
            comp["queue"] = {"status": "unknown"}
    if heartbeat is None:
        comp["workers"] = {
            "status": "unknown",
            "detail": "İşçi kalp atışı hiç alınmadı (işçi veya zamanlayıcı çalışmıyor olabilir)",
        }
        comp["scheduler"] = {"status": "unknown"}
    else:
        stale = now - heartbeat > HEARTBEAT_STALE
        comp["workers"] = {
            "status": "down" if stale else "ok",
            "last_heartbeat": heartbeat.isoformat(),
        }
        comp["scheduler"] = {
            "status": "down" if stale else "ok",
            "last_heartbeat": heartbeat.isoformat(),
        }

    if settings.football_provider == "none":
        comp["football_api"] = {
            "status": "not_configured",
            "detail": "M-G1: veri sağlayıcı anahtarı bekleniyor",
        }
    else:
        last = (
            await db.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
        ).scalar_one_or_none()
        comp["football_api"] = {
            "status": "unknown"
            if last is None
            else ("ok" if last.status in ("succeeded", "skipped") else "degraded"),
            "provider": settings.football_provider,
            "last_run": {
                "job": last.job,
                "status": last.status,
                "at": last.started_at.isoformat(),
                "message": last.message,
            }
            if last
            else None,
        }

    if settings.payment_provider == "none":
        comp["payment_api"] = {"status": "not_configured", "detail": "Satış kapalı (M-G5)"}
    else:
        comp["payment_api"] = {
            "status": "ok",
            "provider": settings.payment_provider,
            "test_mode": settings.payment_provider == "simulator" or settings.payments_test_mode,
            "detail": "Yapılandırıldı; sağlayıcıya bağlantı ödeme anında denetlenir",
        }

    hour = await metrics.window(60)
    comp["backend"] = {
        "status": "ok" if (hour["error_rate"] or 0) < 0.02 else "degraded",
        "window": hour,
        "last_5m": await metrics.window(5),
    }
    overall = "ok"
    for c in comp.values():
        if c["status"] == "down":
            overall = "down"
            break
        if c["status"] == "degraded":
            overall = "degraded"
    return {
        "status": overall,
        "checked_at": now.astimezone(UTC).isoformat(),
        "environment": settings.environment,
        "components": comp,
        "host": host_resources(),
        "costs": {
            "api": None,
            "server": None,
            "note": "Maliyet verisi bağlı değil (sağlayıcı faturası/izleme entegrasyonu yok)",
        },
    }
