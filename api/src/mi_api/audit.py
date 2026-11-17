"""Denetim kaydı yazımı. Hash zinciri veritabanı tetikleyicisinde hesaplanır.

Kayıtlar aynı veritabanı işleminde yazılır: işlem geri alınırsa kayıt da geri alınır, işlem
başarılıysa kayıt silinemez/değiştirilemez (tetikleyici).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.logs import redact

ActorType = Literal["system", "user", "admin", "webhook", "worker"]


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor_type: ActorType,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO audit_log (actor_type, actor_id, action, target_type, target_id, ip,"
            " user_agent, details, prev_hash, hash) VALUES (:actor_type, :actor_id, :action,"
            " :target_type, :target_id, CAST(:ip AS inet), :user_agent, CAST(:details AS jsonb),"
            " '\\x'::bytea, '\\x'::bytea)"
        ),
        {
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "ip": ip,
            "user_agent": (user_agent or "")[:512] or None,
            "details": _json(redact(details or {})),
        },
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def verify_chain(db: AsyncSession) -> int | None:
    """Zincir sağlamsa None, değilse kırık ilk kaydın id'si."""
    result = await db.execute(text("SELECT audit_log_verify()"))
    value = result.scalar_one()
    return int(value) if value is not None else None
