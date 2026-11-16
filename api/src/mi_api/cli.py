"""``mi-admin``: işletim komutları.

* ``migrate``: geçişleri uygular.
* ``bootstrap --email --name``: ilk SUPER_ADMIN'i oluşturur. **Varsayılan parola yoktur:** hesap
  parolasız açılır, tek kullanımlık (24 saat) parola belirleme bağlantısı ekrana yazılır. Kişi
  parolasını belirler, iki adımlı doğrulamayı açar, sonra yönetim paneline girebilir. Sistemde
  zaten aktif bir SUPER_ADMIN varsa reddedilir (sonrakiler panelden atanır).
* ``audit-verify``: denetim kaydı zincirini doğrular.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from mi_api import audit
from mi_api.config import Settings
from mi_api.db import Database
from mi_api.migrate import upgrade
from mi_api.models import EmailToken, User, UserRole
from mi_api.security import new_token, token_digest


async def bootstrap(settings: Settings, email: str, name: str) -> str:
    db = Database(settings.database_url.get_secret_value(), pool_size=1)
    try:
        async with db.session() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('mi.super_admin'))"))
            existing = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM user_roles ur JOIN users u ON u.id = ur.user_id"
                        " WHERE ur.role_code = 'SUPER_ADMIN' AND u.status = 'active'"
                    )
                )
            ).scalar_one()
            if existing:
                raise SystemExit("Zaten aktif bir SUPER_ADMIN var; yeni yöneticiyi panelden atayın")
            email = email.strip().lower()
            now = datetime.now(UTC)
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                user = User(
                    id=uuid.uuid4(), email=email, display_name=name, status="active",
                    email_verified_at=now,
                )  # fmt: skip
                session.add(user)
                await session.flush()
            elif user.status != "active":
                raise SystemExit("Bu e-postadaki hesap aktif değil")
            session.add(UserRole(user_id=user.id, role_code="SUPER_ADMIN"))
            token = new_token()
            session.add(
                EmailToken(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    purpose="password_reset",
                    token_digest=token_digest(token),
                    created_at=now,
                    expires_at=now + timedelta(hours=24),
                )
            )
            await audit.record(
                session, "system.super_admin_bootstrapped", actor_type="system",
                target_type="user", target_id=str(user.id),
            )  # fmt: skip
        return f"{settings.public_web_url}/sifre-sifirla?token={token}"
    finally:
        await db.close()


async def audit_verify(settings: Settings) -> int | None:
    db = Database(settings.database_url.get_secret_value(), pool_size=1)
    try:
        async with db.session() as session:
            return await audit.verify_chain(session)
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mi-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Veritabanı geçişlerini uygula")
    boot = sub.add_parser("bootstrap", help="İlk SUPER_ADMIN'i oluştur")
    boot.add_argument("--email", required=True)
    boot.add_argument("--name", required=True)
    sub.add_parser("audit-verify", help="Denetim kaydı zincirini doğrula")
    args = parser.parse_args(argv)
    settings = Settings()

    if args.command == "migrate":
        upgrade(settings.database_url.get_secret_value())
        print("Geçişler uygulandı.")
    elif args.command == "bootstrap":
        link = asyncio.run(bootstrap(settings, args.email, args.name))
        print("SUPER_ADMIN oluşturuldu. Parola belirleme bağlantısı (24 saat, tek kullanım):")
        print(link)
        print("Sonra: giriş → Hesap → İki adımlı doğrulama → Yönetim paneli.")
    elif args.command == "audit-verify":
        broken = asyncio.run(audit_verify(settings))
        if broken is None:
            print("Denetim kaydı zinciri sağlam.")
        else:
            print(f"Denetim kaydı zinciri {broken} numaralı kayıtta kırık!", file=sys.stderr)
            raise SystemExit(2)


if __name__ == "__main__":
    main()
