"""Prometheus metin biçiminde ``/metrics`` (merkezi izleme için).

Uç yalnızca ``MI_METRICS_TOKEN`` ayarlıysa açıktır ve ``Authorization: Bearer <jeton>`` ister;
web vekili bu yolu dışarı açmaz (yalnızca ``/v1`` ve ``/admin/v1``). Tüm değerler gerçek
kaynaklardan anlık hesaplanır (gauge): istek istatistikleri dakikalık kovalardan, bileşen
durumları System Health anlık görüntüsünden, iş ölçüleri veritabanından. Bilinmeyen değer
yazılmaz (ör. hiç kalp atışı yoksa yaş metriği yoktur) — sıfır uydurulmaz.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.billing.models import Subscription
from mi_api.config import Settings
from mi_api.models import User
from mi_api.ops import health
from mi_api.ops.metrics import Metrics
from mi_api.ops.models import ApprovalRequest, Backup


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class _Out:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen: set[str] = set()

    def add(self, name: str, help_: str, value: float | None, **labels: str) -> None:
        if value is None:
            return
        if name not in self.seen:
            self.seen.add(name)
            self.lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
        lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
        self.lines.append(f"{name}{{{lab}}} {value:g}" if lab else f"{name} {value:g}")


async def render(
    db: AsyncSession, settings: Settings, redis: Redis | None, metrics: Metrics, now: datetime
) -> str:
    out = _Out()
    snap = await health.snapshot(db, settings, redis, metrics, now)
    for name, comp in snap["components"].items():
        status = comp.get("status")
        out.add(
            "mi_component_configured",
            "Bileşen yapılandırılmış mı (1/0)",
            0 if status == "not_configured" else 1,
            component=name,
        )
        if status not in ("not_configured", "unknown"):
            out.add(
                "mi_component_up",
                "Bileşen sağlıklı mı (1/0)",
                1 if status == "ok" else 0,
                component=name,
            )
    db_lat = snap["components"].get("database", {}).get("latency_ms")
    out.add("mi_database_latency_ms", "Veritabanı ping gecikmesi (ms)", db_lat)
    out.add(
        "mi_queue_depth",
        "Celery kuyruğundaki iş sayısı",
        snap["components"].get("queue", {}).get("depth"),
    )
    hb = snap["components"].get("workers", {}).get("last_heartbeat")
    if hb:
        out.add(
            "mi_worker_heartbeat_age_seconds",
            "Son işçi kalp atışından bu yana geçen süre",
            (now - datetime.fromisoformat(hb)).total_seconds(),
        )
    for minutes in (1, 5, 60):
        w = await metrics.window(minutes)
        win = f"{minutes}m"
        out.add("mi_http_requests", "Penceredeki istek sayısı", w["requests"], window=win)
        out.add("mi_http_errors_5xx", "Penceredeki 5xx sayısı", w["errors_5xx"], window=win)
        out.add(
            "mi_http_latency_avg_ms",
            "Penceredeki ortalama yanıt süresi (ms)",
            w["avg_ms"],
            window=win,
        )
        out.add(
            "mi_http_latency_max_ms",
            "Penceredeki en uzun yanıt süresi (ms)",
            w["max_ms"],
            window=win,
        )

    out.add(
        "mi_users",
        "Kayıtlı kullanıcı sayısı",
        (await db.execute(select(func.count()).select_from(User))).scalar_one(),
    )
    subs: Any = await db.execute(
        select(Subscription.plan_code, func.count())
        .where(Subscription.status == "active", Subscription.current_period_end > now)
        .group_by(Subscription.plan_code)
    )
    for plan, n in subs.all():
        out.add("mi_subscriptions_active", "Etkin abonelik sayısı", n, plan=plan)
    pending = (
        await db.execute(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.status == "pending", ApprovalRequest.expires_at > now)
        )
    ).scalar_one()
    out.add("mi_approvals_pending", "Bekleyen dört göz talebi", pending)
    out.add(
        "mi_backup_configured",
        "Yedekleme yapılandırılmış mı (1/0)",
        1 if settings.backup_dir else 0,
    )
    last_ok = (
        await db.execute(
            select(Backup)
            .where(Backup.status.in_(("ok", "pruned")))
            .order_by(Backup.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_ok is not None:
        out.add(
            "mi_backup_last_success_timestamp_seconds",
            "Son başarılı yedeğin zamanı (unix)",
            last_ok.created_at.timestamp(),
        )
        if last_ok.verify_ok is not None:
            out.add(
                "mi_backup_last_verify_ok",
                "Son yedeğin geri yükleme doğrulaması (1/0)",
                1 if last_ok.verify_ok else 0,
            )
    return "\n".join(out.lines) + "\n"
