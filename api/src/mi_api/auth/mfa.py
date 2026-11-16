"""MFA doğrulaması: TOTP kodu veya tek kullanımlık kurtarma kodu."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.context import Services
from mi_api.errors import ApiError
from mi_api.models import RecoveryCode, User
from mi_api.security import SecretBox, recovery_digest, verify_totp


def mfa_aad(user: User) -> str:
    return f"mfa|{user.id}"


def require_box(services: Services) -> SecretBox:
    if services.box is None:
        raise ApiError(503, "mfa_unavailable", "İki adımlı doğrulama bu sunucuda yapılandırılmamış")
    return services.box


async def check_mfa(db: AsyncSession, services: Services, user: User, code: str) -> str | None:
    """Kod geçerliyse yöntemi (``totp`` / ``recovery``) döner; değilse None.

    Başarılı TOTP'de kullanılan zaman adımı kaydedilir (aynı kod ikinci kez kabul edilmez);
    kurtarma kodu kullanıldı olarak işaretlenir.
    """
    if user.mfa_enabled_at is None or user.mfa_secret_enc is None:
        return None
    box = require_box(services)
    cleaned = "".join(code.split())
    if cleaned.isdigit():
        secret = box.open(user.mfa_secret_enc, mfa_aad(user))
        counter = verify_totp(
            secret, cleaned, last_counter=user.mfa_last_counter, now=services.clock().timestamp()
        )
        if counter is None:
            return None
        user.mfa_last_counter = counter
        return "totp"
    if len(cleaned) > 16:
        return None
    row = (
        await db.execute(
            select(RecoveryCode)
            .where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_digest == recovery_digest(cleaned),
                RecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.used_at = services.clock()
    return "recovery"
