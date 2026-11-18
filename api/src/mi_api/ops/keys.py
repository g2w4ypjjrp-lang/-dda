"""Gizli anahtar (MI_SECRET_KEK) döndürme.

KEK, yöneticilerin ve kullanıcıların MFA (TOTP) sırlarını AES-256-GCM ile şifreler
(``users.mfa_secret_enc``, ek veri ``mfa|<kullanıcı kimliği>``). Döndürme:

1. Yeni anahtar üretilir ve **ortam değişkeniyle** verilir (``MI_NEW_SECRET_KEK``; komut satırına
   yazılmaz, süreç listesinde görünmez).
2. ``mi-admin rotate-kek``: tek işlemde her sır eski anahtarla çözülür, yenisiyle şifrelenir ve
   yeniden çözülerek doğrulanır. **Tek bir sır bile çözülemezse hiçbir şey değişmez.**
   Zaten yeni anahtarla açılan sırlar atlanır (yarıda kalan / tekrar çalıştırılan döndürme güvenli).
3. ``MI_SECRET_KEK`` yeni değerle güncellenir ve API/işçi yeniden başlatılır. Döndürme ile yeniden
   başlatma arasında eski anahtarla çalışan süreçler MFA doğrulayamaz: işlem bakım penceresinde,
   API durdurulmuşken yapılmalıdır (docs/calistirma-kilavuzu.md §9).
"""

from __future__ import annotations

import base64
from typing import Any

from cryptography.exceptions import InvalidTag
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api import audit
from mi_api.security import SecretBox


class KeyRotationError(RuntimeError):
    pass


def decode_kek(value: str, name: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise KeyRotationError(f"{name} base64 değil") from exc
    if len(raw) != 32:
        raise KeyRotationError(f"{name} 32 bayt olmalı ({len(raw)} bayt)")
    return raw


def _aad(user_id: Any) -> str:
    return f"mfa|{user_id}"  # auth.mfa.mfa_aad ile aynı


async def rotate(
    db: AsyncSession, old: bytes, new: bytes, *, dry_run: bool = False
) -> dict[str, int]:
    if old == new:
        raise KeyRotationError("Yeni anahtar eskisiyle aynı")
    old_box, new_box = SecretBox(old), SecretBox(new)
    rows = (
        await db.execute(
            text(
                "SELECT id, mfa_secret_enc FROM users"
                " WHERE mfa_secret_enc IS NOT NULL ORDER BY id FOR UPDATE"
            )
        )
    ).all()
    updates: list[tuple[Any, bytes]] = []
    already = 0
    failed: list[str] = []
    for user_id, blob in rows:
        aad = _aad(user_id)
        try:
            secret = old_box.open(bytes(blob), aad)
        except InvalidTag:
            try:
                new_box.open(bytes(blob), aad)
                already += 1
            except InvalidTag:
                failed.append(str(user_id))
            continue
        sealed = new_box.seal(secret, aad)
        # AES-GCM'de beklenmez; yine de yazmadan önce yeni anahtarla açılabildiğini doğrula.
        if new_box.open(sealed, aad) != secret:  # pragma: no cover
            raise KeyRotationError("Yeniden şifreleme doğrulanamadı")
        updates.append((user_id, sealed))
    if failed:
        raise KeyRotationError(
            f"{len(failed)} MFA sırrı ne eski ne yeni anahtarla açılabildi; hiçbir şey"
            f" değiştirilmedi (ilk kimlikler: {', '.join(failed[:3])})"
        )
    if not dry_run:
        for user_id, sealed in updates:
            await db.execute(
                text("UPDATE users SET mfa_secret_enc = :b WHERE id = :u"),
                {"b": sealed, "u": user_id},
            )
        await audit.record(
            db,
            "system.kek_rotated",
            actor_type="system",
            details={"rotated": len(updates), "already_rotated": already},
        )
    return {
        "secrets": len(rows),
        "rotated": len(updates),
        "already_rotated": already,
        "dry_run": int(dry_run),
    }
