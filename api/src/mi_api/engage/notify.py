# ruff: noqa: E501
"""Bildirim servisi: kategori tercihine göre uygulama içi bildirim ve e-posta kuyruğu.

* Kategoriler: ``system`` (duyuru), ``match`` (favori takım/maç başlıyor), ``result`` (favori maç
  bitti), ``subscription`` (paket etkinleşti, iade, süre bitiyor), ``security`` (yeni cihaz/IP'den
  giriş, parola ve MFA değişikliği), ``coupon`` (kupon sonuçlandı).
* Varsayılan: uygulama içi tüm kategorilerde açık; e-posta yalnızca güvenlikte açık. Kullanıcı
  değiştirebilir; **güvenlik bildirimleri uygulama içinde kapatılamaz**.
* E-posta ``email_outbox`` kuyruğuna yazılır; gönderim sağlayıcısı bağlanana kadar (M-G6) kuyrukta
  bekler — gönderilmiş gibi gösterilmez.
* ``dedupe_key`` aynı olayın aynı kullanıcıya ikinci kez gitmesini engeller (benzersiz indeks).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.engage.models import Notification, NotificationPref
from mi_api.models import EmailOutbox, User

CATEGORIES = ("system", "match", "result", "subscription", "security", "coupon")
LABELS = {
    "system": "Sistem duyuruları",
    "match": "Favori maç başlıyor",
    "result": "Favori maç sonucu",
    "subscription": "Abonelik",
    "security": "Güvenlik",
    "coupon": "Kupon sonuçları",
}
DEFAULT_EMAIL = {"security"}


async def prefs_for(db: AsyncSession, user_id: uuid.UUID) -> dict[str, dict[str, bool]]:
    rows = {
        p.category: p
        for p in (
            await db.execute(select(NotificationPref).where(NotificationPref.user_id == user_id))
        ).scalars()
    }
    out = {}
    for c in CATEGORIES:
        p = rows.get(c)
        out[c] = {
            "in_app": True if c == "security" else (p.in_app if p else True),
            "email": p.email if p else c in DEFAULT_EMAIL,
        }
    return out


async def notify(
    db: AsyncSession,
    user_id: uuid.UUID,
    category: str,
    title: str,
    body: str,
    *,
    now: datetime,
    link: str | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Bildirim üretir; tekrar (dedupe) veya tercih kapalıysa ``False``."""
    if category not in CATEGORIES:
        raise ValueError(f"Bilinmeyen bildirim kategorisi: {category}")
    prefs = (await prefs_for(db, user_id))[category]
    created = False
    if prefs["in_app"]:
        stmt = (
            insert(Notification)
            .values(user_id=user_id, category=category, title=title[:160], body=body[:600], link=link,
                    dedupe_key=dedupe_key, created_at=now)
            .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"], index_where=Notification.dedupe_key.is_not(None))
            .returning(Notification.id)
        )  # fmt: skip
        created = (await db.execute(stmt)).scalar_one_or_none() is not None
    if prefs["email"] and (created or not prefs["in_app"]):
        user = await db.get(User, user_id)
        if user is not None and user.status == "active" and user.email_verified_at is not None:
            db.add(
                EmailOutbox(
                    to_address=user.email,
                    template=f"notify_{category}",
                    payload={"title": title, "body": body, "link": link},
                    status="pending",
                )
            )
    return created


async def login_alert(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, ip: str | None, now: datetime
) -> None:
    """Son 90 günde görülmemiş bir IP'den giriş: güvenlik bildirimi (ilk giriş hariç)."""
    from datetime import timedelta

    from mi_api.models import UserSession

    others = (
        await db.execute(
            select(UserSession.ip).where(
                UserSession.user_id == user_id, UserSession.id != session_id,
                UserSession.created_at >= now - timedelta(days=90),
            )
        )
    ).scalars().all()  # fmt: skip
    if not others or ip is None or any(str(o) == ip for o in others if o is not None):
        return
    await notify(
        db, user_id, "security", "Yeni bir konumdan giriş yapıldı",
        f"Hesabınıza {ip} adresinden giriş yapıldı. Siz değilseniz parolanızı değiştirin ve açık oturumları kapatın.",
        now=now, link="/panel", dedupe_key=f"login:{session_id}",
    )  # fmt: skip


SECURITY_MESSAGES = {
    "auth.password_reset": (
        "Parolanız sıfırlandı",
        "Tüm oturumlar kapatıldı. Bu işlemi siz yapmadıysanız hemen destek ile iletişime geçin.",
    ),
    "auth.password_changed": (
        "Parolanız değiştirildi",
        "Diğer cihazlardaki oturumlar kapatıldı. Bu işlemi siz yapmadıysanız hemen parolanızı sıfırlayın.",
    ),
    "auth.mfa_enabled": (
        "İki adımlı doğrulama açıldı",
        "Hesabınız artık giriş sırasında doğrulama kodu istiyor.",
    ),
    "auth.mfa_disabled": (
        "İki adımlı doğrulama kapatıldı",
        "Bu işlemi siz yapmadıysanız hemen parolanızı değiştirip doğrulamayı yeniden açın.",
    ),
}


async def security_event(db: AsyncSession, user_id: uuid.UUID, action: str, now: datetime) -> None:
    title, body = SECURITY_MESSAGES[action]
    await notify(
        db,
        user_id,
        "security",
        title,
        body,
        now=now,
        link="/panel",
        dedupe_key=f"{action}:{int(now.timestamp())}",
    )
