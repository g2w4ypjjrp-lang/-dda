"""Özellik bayrakları: yönetim panelinden açılıp kapatılan, **backend'de** uygulanan anahtarlar.

Kapalı bir bayrak ilgili uç noktayı 503 ``feature_disabled`` ile durdurur (ör. kayıt, kupon,
sanal portföy, satın alma). Bayrak satırı yoksa özellik açık sayılır (geçiş tohumlar).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.errors import ApiError
from mi_api.ops.models import FeatureFlag

MESSAGES = {
    "registration_open": "Yeni üye kaydı geçici olarak kapalı.",
    "coupons_enabled": "Kupon oluşturucu geçici olarak kapalı.",
    "virtual_enabled": "Sanal portföy işlemleri geçici olarak kapalı.",
    "sales_enabled": "Satın alma geçici olarak kapalı.",
}


async def is_enabled(db: AsyncSession, key: str) -> bool:
    flag = await db.get(FeatureFlag, key)
    return True if flag is None else flag.enabled


async def require(db: AsyncSession, key: str) -> None:
    if not await is_enabled(db, key):
        flag = await db.get(FeatureFlag, key)
        detail = (flag.message if flag and flag.message else None) or MESSAGES.get(
            key, "Bu özellik geçici olarak kapalı."
        )
        raise ApiError(503, "feature_disabled", detail)
