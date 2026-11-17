"""Plan hakları (entitlements): etkin plan, hak değerleri, günlük kullanım sayaçları.

Haklar veritabanından okunur (yönetim panelinden değiştirilebilir); kontrol **her zaman backend'de**
yapılır. Oturum açmamış ziyaretçi FREE haklarıyla değerlendirilir. Birden fazla etkin abonelik varsa
en yüksek plan geçerlidir. Abonelik süresi bitince kullanıcı kendiliğinden FREE'ye düşer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.billing.models import PlanEntitlement, Subscription, UsageDaily
from mi_api.errors import ApiError
from mi_api.football.api import TR

ORDER = {"FREE": 0, "PRO": 1, "ELITE": 2}
LOCK_LABELS = {
    "predictions.markets": "Tüm piyasalar ve doğru skor olasılıkları",
    "predictions.uncertainty": "Belirsizlik aralıkları",
    "predictions.components": "Model karşılaştırması (bileşen modeller)",
    "coupons.enabled": "Kupon oluşturucu",
    "virtual.kelly": "Kesirli Kelly ile sanal simülasyon",
}

# Yönetim panelinden değiştirilebilen haklar ve tipleri (int: 0..üst sınır).
ENTITLEMENTS: dict[str, tuple[type, int]] = {
    "predictions.markets": (bool, 1),
    "predictions.uncertainty": (bool, 1),
    "predictions.components": (bool, 1),
    "coupons.enabled": (bool, 1),
    "coupons.daily_generate": (int, 10_000),
    "coupons.max_legs": (int, 10),
    "virtual.enabled": (bool, 1),
    "virtual.kelly": (bool, 1),
    "history.days": (int, 3650),
}


def validate_entitlement(key: str, value: Any) -> Any:
    if key not in ENTITLEMENTS:
        raise ApiError(422, "unknown_entitlement", f"Bilinmeyen hak: {key}")
    kind, upper = ENTITLEMENTS[key]
    if kind is bool:
        if not isinstance(value, bool):
            raise ApiError(422, "invalid_entitlement", f"{key} true/false olmalı")
        return value
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
        raise ApiError(422, "invalid_entitlement", f"{key} 0 ile {upper} arasında tam sayı olmalı")
    return value


@dataclass(frozen=True)
class Access:
    plan: str
    values: dict[str, Any]
    subscription_id: int | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def allows(self, key: str) -> bool:
        return bool(self.values.get(key, False))


async def plan_values(db: AsyncSession, plan: str) -> dict[str, Any]:
    rows = (
        await db.execute(select(PlanEntitlement).where(PlanEntitlement.plan_code == plan))
    ).scalars()
    return {r.key: r.value for r in rows}


async def active_subscription(
    db: AsyncSession, user_id: uuid.UUID, now: datetime
) -> Subscription | None:
    subs = (
        (
            await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(
                        ("active", "canceled")
                    ),  # iptal edilen dönem sonuna kadar geçerli
                    Subscription.current_period_end > now,
                )
            )
        )
        .scalars()
        .all()
    )
    if not subs:
        return None
    return max(subs, key=lambda s: (ORDER.get(s.plan_code, 0), s.current_period_end))


async def access_for(db: AsyncSession, user_id: uuid.UUID | None, now: datetime) -> Access:
    sub = await active_subscription(db, user_id, now) if user_id else None
    plan = sub.plan_code if sub else "FREE"
    return Access(plan, await plan_values(db, plan), sub.id if sub else None)


def required_plan(key: str) -> str:
    return "ELITE" if key in ("predictions.components", "virtual.kelly") else "PRO"


def plan_required(key: str) -> ApiError:
    return ApiError(
        403, "plan_required",
        f"{LOCK_LABELS.get(key, key)} {required_plan(key)} paketinde. Paketinizi yükseltin.",
    )  # fmt: skip


async def consume(
    db: AsyncSession, user_id: uuid.UUID, key: str, limit: int | None, now: datetime
) -> int:
    """Günlük sayacı bir artırır (Türkiye günü). Sınır doluysa hata; ``None`` sınırsız."""
    day = now.astimezone(TR).date()
    stmt: Any = insert(UsageDaily).values(user_id=user_id, day=day, key=key, count=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UsageDaily.user_id, UsageDaily.day, UsageDaily.key],
        set_={"count": UsageDaily.count + 1},
    ).returning(UsageDaily.count)
    count = int((await db.execute(stmt)).scalar_one())
    if limit is not None and count > limit:
        raise ApiError(
            429,
            "daily_limit",
            f"Günlük kullanım sınırınız doldu ({limit}). Paketinizi yükseltebilirsiniz.",
        )
    return count


async def usage_today(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> dict[str, int]:
    day = now.astimezone(TR).date()
    rows = (
        await db.execute(
            select(UsageDaily).where(UsageDaily.user_id == user_id, UsageDaily.day == day)
        )
    ).scalars()
    return {r.key: r.count for r in rows}
