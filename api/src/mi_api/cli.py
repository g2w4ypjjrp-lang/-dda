"""``mi-admin``: işletim komutları.

* ``migrate``: geçişleri uygular.
* ``bootstrap --email --name``: ilk SUPER_ADMIN'i oluşturur. **Varsayılan parola yoktur:** hesap
  parolasız açılır, tek kullanımlık (24 saat) parola belirleme bağlantısı ekrana yazılır. Kişi
  parolasını belirler, iki adımlı doğrulamayı açar, sonra yönetim paneline girebilir. Sistemde
  zaten aktif bir SUPER_ADMIN varsa reddedilir (sonrakiler panelden atanır).
* ``audit-verify``: denetim kaydı zincirini doğrular.
* ``football-sync JOB [--date] [--fixture-id] [--competition-id] [--season]``: futbol verisi işini
  elle çalıştırır (ör. tarihsel veri yükleme). Sonuç ``football_sync_runs``'a da yazılır.
* ``grant-plan --email --plan PRO|ELITE --days N``: kullanıcıya ödemesiz abonelik verir (destek,
  test, kurumsal). Denetim kaydına yazılır; panelden de yapılabilir.
* ``backup [--no-verify]``: ``MI_BACKUP_DIR`` altına yedek alır, sonra geçici veritabanına geri
  yükleyerek doğrular (``mi_api.ops.backup``).
* ``backup-verify [--id N] [--no-restore]``: bir yedeği (varsayılan: en son) yeniden doğrular.
* ``restore FILE --target-url URL --yes [--overwrite-current]``: yedeği geri yükler.
* ``rotate-kek [--dry-run]``: MFA sırlarını ``MI_SECRET_KEK``'ten ``MI_NEW_SECRET_KEK``'e taşır
  (``mi_api.ops.keys``; API durdurulmuşken).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from mi_api import aio, audit
from mi_api.config import Settings
from mi_api.db import Database
from mi_api.football.sync import JOBS
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


async def grant_plan(settings: Settings, email: str, plan: str, days: int) -> str:
    from mi_api.billing.service import grant_subscription

    db = Database(settings.database_url.get_secret_value(), pool_size=1)
    try:
        async with db.session() as session:
            user = (
                await session.execute(select(User).where(User.email == email.strip().lower()))
            ).scalar_one_or_none()
            if user is None:
                raise SystemExit("Bu e-postada kullanıcı yok")
            now = datetime.now(UTC)
            sub = await grant_subscription(
                session, user_id=user.id, plan=plan, days=days, source="admin", now=now
            )
            await audit.record(
                session, "billing.subscription_granted", actor_type="system",
                target_type="user", target_id=str(user.id),
                details={"plan": plan, "days": days, "subscription_id": sub.id, "via": "cli"},
            )  # fmt: skip
            return sub.current_period_end.isoformat()
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
    grant = sub.add_parser("grant-plan", help="Kullanıcıya ödemesiz abonelik ver")
    grant.add_argument("--email", required=True)
    grant.add_argument("--plan", required=True, choices=["PRO", "ELITE"])
    grant.add_argument("--days", required=True, type=int)
    fsync = sub.add_parser("football-sync", help="Futbol verisi işini elle çalıştır")
    fsync.add_argument("job", choices=JOBS)
    fsync.add_argument("--date")
    fsync.add_argument("--fixture-id", type=int)
    fsync.add_argument("--competition-id", type=int)
    fsync.add_argument("--season", type=int)
    bk = sub.add_parser("backup", help="Veritabanı yedeği al ve doğrula")
    bk.add_argument("--no-verify", action="store_true")
    bv = sub.add_parser(
        "backup-verify", help="Yedeği doğrula (geçici veritabanına geri yükleyerek)"
    )
    bv.add_argument("--id", type=int)
    bv.add_argument("--no-restore", action="store_true")
    rs = sub.add_parser("restore", help="Yedeği bir veritabanına geri yükle")
    rs.add_argument("file")
    rs.add_argument("--target-url", required=True)
    rs.add_argument("--yes", action="store_true", help="Hedefteki verinin silineceğini onaylıyorum")
    rs.add_argument("--overwrite-current", action="store_true")
    rk = sub.add_parser("rotate-kek", help="MFA sırlarını yeni anahtarla yeniden şifrele")
    rk.add_argument("--dry-run", action="store_true", help="Yalnızca denetle, yazma")
    args = parser.parse_args(argv)
    settings = Settings()

    if args.command == "migrate":
        upgrade(settings.database_url.get_secret_value())
        print("Geçişler uygulandı.")
    elif args.command == "bootstrap":
        link = aio.run(bootstrap(settings, args.email, args.name))
        print("SUPER_ADMIN oluşturuldu. Parola belirleme bağlantısı (24 saat, tek kullanım):")
        print(link)
        print("Sonra: giriş → Hesap → İki adımlı doğrulama → Yönetim paneli.")
    elif args.command == "audit-verify":
        broken = aio.run(audit_verify(settings))
        if broken is None:
            print("Denetim kaydı zinciri sağlam.")
        else:
            print(f"Denetim kaydı zinciri {broken} numaralı kayıtta kırık!", file=sys.stderr)
            raise SystemExit(2)
    elif args.command == "grant-plan":
        if not 1 <= args.days <= 3660:
            raise SystemExit("--days 1 ile 3660 arasında olmalı")
        end = aio.run(grant_plan(settings, args.email, args.plan, args.days))
        print(f"{args.plan} verildi; bitiş: {end}")
    elif args.command == "rotate-kek":
        print(json.dumps(aio.run(rotate_kek(settings, dry_run=args.dry_run)), ensure_ascii=False))
        if not args.dry_run:
            print("Şimdi MI_SECRET_KEK'i yeni değerle güncelleyin ve API/işçiyi yeniden başlatın.")
    elif args.command in ("backup", "backup-verify", "restore"):
        _backup_command(settings, args)
    elif args.command == "football-sync":
        from mi_api.jobs import run_job
        from mi_api.logs import configure_logging

        configure_logging(settings.log_level, json_output=settings.log_json)
        params = {
            k: v
            for k, v in {
                "date": args.date,
                "fixture_id": args.fixture_id,
                "competition_id": args.competition_id,
                "season": args.season,
            }.items()
            if v is not None
        }
        result = aio.run(run_job(args.job, params, trigger="cli"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == "failed":
            raise SystemExit(1)


async def rotate_kek(settings: Settings, *, dry_run: bool) -> dict[str, int]:
    import os

    from mi_api.ops import keys

    try:
        if settings.secret_kek is None:
            raise keys.KeyRotationError("MI_SECRET_KEK ayarlı değil")
        new_value = os.environ.get("MI_NEW_SECRET_KEK")
        if not new_value:
            raise keys.KeyRotationError("MI_NEW_SECRET_KEK ortam değişkeni gerekli")
        old = keys.decode_kek(settings.secret_kek.get_secret_value(), "MI_SECRET_KEK")
        new = keys.decode_kek(new_value, "MI_NEW_SECRET_KEK")
        db = Database(settings.database_url.get_secret_value(), pool_size=1)
        try:
            async with db.session() as session:
                return await keys.rotate(session, old, new, dry_run=dry_run)
        finally:
            await db.close()
    except keys.KeyRotationError as exc:
        raise SystemExit(str(exc)) from exc


def _backup_command(settings: Settings, args: argparse.Namespace) -> None:
    from pathlib import Path

    from mi_api.ops import backup

    try:
        if args.command == "backup":
            out = aio.run(backup.create(settings, "cli", verify_after=not args.no_verify))
            print(
                json.dumps(
                    {"id": out.id, "status": out.status, **out.detail}, ensure_ascii=False, indent=2
                )
            )
            if out.status != "ok" or out.detail.get("verify", {"ok": True}).get("ok") is False:
                raise SystemExit(1)
        elif args.command == "backup-verify":
            res = aio.run(backup.verify(settings, args.id, restore=not args.no_restore))
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
            if not res["ok"]:
                raise SystemExit(1)
        else:
            if not args.yes:
                raise SystemExit(
                    "Geri yükleme hedefteki veriyi siler; onaylamak için --yes ekleyin"
                )
            backup.restore(
                settings, Path(args.file), args.target_url, overwrite_current=args.overwrite_current
            )
            print("Geri yükleme tamamlandı. Sonra: mi-admin migrate && mi-admin audit-verify")
    except backup.BackupError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
