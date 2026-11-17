# ruff: noqa: E501, ASYNC240
"""Yedekleme, doğrulama ve geri yükleme (PostgreSQL ``pg_dump`` / ``pg_restore``).

* **Yedek** (``mi-admin backup``, işçide günlük ``mi.backup``): ``pg_dump --format=custom`` ile
  ``MI_BACKUP_DIR`` altına ``mi-YYYYmmddTHHMMSSZ-xxxxxx.dump``; dosya önce ``.part`` adıyla yazılır,
  bitince yeniden adlandırılır (yarım dosya yedek sayılmaz). SHA-256 özeti hem ``backups``
  tablosuna hem ``.sha256`` yan dosyasına yazılır. Son ``MI_BACKUP_KEEP`` başarılı yedek tutulur.
* **Doğrulama** (``mi-admin backup-verify``, yedekten sonra otomatik): özet karşılaştırılır,
  arşiv içeriği listelenir, sonra yedek **geçici bir veritabanına gerçekten geri yüklenir** ve
  orada geçiş sürümü, tablo sayısı, temel satır sayıları ve denetim kaydı hash zinciri denetlenir;
  geçici veritabanı silinir. ``CREATE DATABASE`` yetkisi yoksa geri yükleme denenmez ve sonuç
  bunu açıkça söyler (doğrulandı sayılmaz).
* **Geri yükleme** (``mi-admin restore``) yalnızca komut satırından, açık onayla; hedef çalışan
  veritabanıysa ayrıca ``--overwrite-current`` ister.

Parola süreç listesinde görünmesin diye bağlantı bilgisi komut satırıyla değil ``PG*`` ortam
değişkenleriyle verilir; hata metinleri kayda kısaltılarak yazılır.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from sqlalchemy import select
from sqlalchemy.engine import make_url

from mi_api import audit
from mi_api.config import Settings
from mi_api.db import Database
from mi_api.ops.models import Backup

TIMEOUT_S = 3600
CORE_TABLES = (
    "users",
    "audit_log",
    "orders",
    "subscriptions",
    "fixtures",
    "ml_predictions",
    "coupons",
)


class BackupError(RuntimeError):
    pass


def pg_env(dsn: str, database: str | None = None) -> dict[str, str]:
    url = make_url(dsn)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(
        {
            "PGHOST": url.host or "127.0.0.1",
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "",
            "PGPASSWORD": url.password or "",
            "PGDATABASE": database or url.database or "",
        }
    )
    q = url.query
    for key, var in (
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("sslcert", "PGSSLCERT"),
        ("sslkey", "PGSSLKEY"),
    ):
        value = q.get(key)
        if isinstance(value, str):
            env[var] = value
    return env


def conninfo(dsn: str, database: str | None = None) -> str:
    url = make_url(dsn).set(drivername="postgresql")
    if database:
        url = url.set(database=database)
    return url.render_as_string(hide_password=False)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tail(stderr: str) -> str:
    return stderr.strip()[-500:] or "bilinmeyen hata"


def _run(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # Komut ve argümanlar sabit; yalnızca dosya yolları ayarlardan gelir (kabuk kullanılmaz).
    return subprocess.run(  # noqa: S603
        cmd, env=env, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
    )


@dataclass
class Outcome:
    id: int
    status: str
    file: str | None
    detail: dict[str, Any]


async def create(settings: Settings, trigger: str = "cli", *, verify_after: bool = True) -> Outcome:
    if not settings.backup_dir:
        raise BackupError("MI_BACKUP_DIR ayarlı değil; yedek alınmadı")
    folder = Path(settings.backup_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    dsn = settings.database_url.get_secret_value()
    now = datetime.now(UTC)
    # Aynı saniyede iki yedek çakışmasın (budama yanlış dosyayı silmesin) diye rastgele ek.
    name = f"mi-{now:%Y%m%dT%H%M%S}Z-{secrets.token_hex(3)}.dump"
    final, part = folder / name, folder / f"{name}.part"
    started = time.monotonic()
    proc = _run(
        [
            "pg_dump",
            "--format=custom",
            "--compress=6",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(part),
        ],
        pg_env(dsn),
    )
    duration = int((time.monotonic() - started) * 1000)
    db = Database(dsn, pool_size=1)
    try:
        if proc.returncode != 0:
            part.unlink(missing_ok=True)
            async with db.session() as s:
                row = Backup(
                    created_at=now,
                    file_name=name,
                    status="failed",
                    duration_ms=duration,
                    error=_tail(proc.stderr),
                    trigger=trigger,
                )
                s.add(row)
                await s.flush()
                await audit.record(
                    s,
                    "system.backup_failed",
                    actor_type="system",
                    target_type="backup",
                    target_id=str(row.id),
                    details={"error": row.error},
                )
                return Outcome(row.id, "failed", None, {"error": row.error})
        os.replace(part, final)
        final.chmod(0o600)
        digest = sha256_of(final)
        (folder / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
        async with db.session() as s:
            row = Backup(
                created_at=now, file_name=name, size_bytes=final.stat().st_size, sha256=digest,
                status="ok", duration_ms=duration, trigger=trigger,
            )  # fmt: skip
            s.add(row)
            await s.flush()
            await audit.record(
                s, "system.backup_created", actor_type="system", target_type="backup", target_id=str(row.id),
                details={"file": name, "size_bytes": row.size_bytes, "sha256": digest},
            )  # fmt: skip
            backup_id = row.id
            pruned = await _prune(s, folder, settings.backup_keep)
    finally:
        await db.close()
    detail: dict[str, Any] = {"file": name, "sha256": digest, "pruned": pruned}
    if verify_after:
        detail["verify"] = await verify(settings, backup_id)
    return Outcome(backup_id, "ok", str(final), detail)


async def _prune(s: Any, folder: Path, keep: int) -> list[str]:
    old = (
        (
            await s.execute(
                select(Backup)
                .where(Backup.status == "ok")
                .order_by(Backup.created_at.desc())
                .offset(keep)
            )
        )
        .scalars()
        .all()
    )
    names = []
    for row in old:
        for path in (folder / row.file_name, folder / f"{row.file_name}.sha256"):
            path.unlink(missing_ok=True)
        row.status = "pruned"
        names.append(row.file_name)
    return names


async def _restore_probe(dsn: str, file: Path) -> dict[str, Any]:
    """Yedeği geçici bir veritabanına yükler ve orada denetler; veritabanı her durumda silinir."""
    temp = f"mi_verify_{secrets.token_hex(4)}"
    try:
        async with await psycopg.AsyncConnection.connect(conninfo(dsn), autocommit=True) as admin:
            await admin.execute(f'CREATE DATABASE "{temp}"')
    except psycopg.Error as exc:
        return {
            "restore_tested": False,
            "reason": f"geçici veritabanı oluşturulamadı: {str(exc).strip()[:200]}",
        }
    try:
        proc = _run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--dbname",
                temp,
                str(file),
            ],
            pg_env(dsn, temp),
        )
        if proc.returncode != 0:
            return {"restore_tested": True, "restore_ok": False, "error": _tail(proc.stderr)}
        async with await psycopg.AsyncConnection.connect(conninfo(dsn, temp)) as conn:
            version = (
                await (await conn.execute("SELECT version_num FROM alembic_version")).fetchone()
                or [None]
            )[0]
            tables = (
                await (
                    await conn.execute(
                        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                    )
                ).fetchone()
                or [0]
            )[0]
            counts: dict[str, int] = {}
            for t in CORE_TABLES:
                exists = (
                    await (
                        await conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{t}",))
                    ).fetchone()
                    or [False]
                )[0]
                if exists:
                    counts[t] = int(
                        (
                            await (await conn.execute(f'SELECT count(*) FROM "{t}"')).fetchone()  # noqa: S608 (sabit tablo listesi)
                            or [0]
                        )[0]
                    )
            broken = (await (await conn.execute("SELECT audit_log_verify()")).fetchone() or [None])[
                0
            ]
        return {
            "restore_tested": True, "restore_ok": True, "alembic_version": version, "tables": int(tables),
            "rows": counts, "audit_chain_intact": broken is None, "audit_first_broken_id": broken,
        }  # fmt: skip
    finally:
        async with await psycopg.AsyncConnection.connect(conninfo(dsn), autocommit=True) as admin:
            await admin.execute(f'DROP DATABASE IF EXISTS "{temp}" WITH (FORCE)')


async def verify(
    settings: Settings, backup_id: int | None = None, *, restore: bool = True
) -> dict[str, Any]:
    if not settings.backup_dir:
        raise BackupError("MI_BACKUP_DIR ayarlı değil")
    folder = Path(settings.backup_dir)
    dsn = settings.database_url.get_secret_value()
    db = Database(dsn, pool_size=1)
    try:
        async with db.session() as s:
            stmt = select(Backup).where(Backup.status == "ok")
            stmt = (
                stmt.where(Backup.id == backup_id)
                if backup_id
                else stmt.order_by(Backup.created_at.desc()).limit(1)
            )
            row = (await s.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise BackupError("Doğrulanacak başarılı yedek bulunamadı")
            file = folder / row.file_name
            result: dict[str, Any] = {"file": row.file_name}
            if not file.exists():
                result |= {"file_present": False}
            else:
                actual = sha256_of(file)
                result |= {"file_present": True, "sha256_ok": actual == row.sha256}
                listing = _run(["pg_restore", "--list", str(file)], pg_env(dsn))
                result["archive_ok"] = listing.returncode == 0
                result["table_data_entries"] = sum(
                    1 for line in listing.stdout.splitlines() if " TABLE DATA " in line
                )
                if result["sha256_ok"] and result["archive_ok"] and restore:
                    result |= await _restore_probe(dsn, file)
            ok = bool(
                result.get("file_present") and result.get("sha256_ok") and result.get("archive_ok")
                and result.get("restore_ok") and result.get("audit_chain_intact")
            )  # fmt: skip
            row.verified_at = datetime.now(UTC)
            row.verify_ok = ok
            row.verify = result
            await audit.record(
                s, "system.backup_verified", actor_type="system", target_type="backup", target_id=str(row.id),
                details={"ok": ok, "restore_tested": result.get("restore_tested", False)},
            )  # fmt: skip
            result["ok"] = ok
            result["id"] = row.id
            return result
    finally:
        await db.close()


def restore(settings: Settings, file: Path, target_url: str, *, overwrite_current: bool) -> None:
    """Komut satırından geri yükleme. Çalışan veritabanının üzerine yazmak ayrıca onay ister."""
    current = make_url(settings.database_url.get_secret_value())
    target = make_url(target_url)
    same = (current.host, current.port or 5432, current.database) == (
        target.host,
        target.port or 5432,
        target.database,
    )
    if same and not overwrite_current:
        raise BackupError(
            "Hedef çalışan veritabanı; üzerine yazmak için --overwrite-current gerekir (önce hizmetleri durdurun)"
        )
    sidecar = file.with_name(f"{file.name}.sha256")
    if not sidecar.exists():
        raise BackupError(f"Özet dosyası yok: {sidecar.name}")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    if sha256_of(file) != expected:
        raise BackupError("SHA-256 uyuşmuyor; dosya bozuk ya da değiştirilmiş, geri yüklenmedi")
    proc = _run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--single-transaction",
            "--dbname",
            target.database or "",
            str(file),
        ],
        pg_env(target_url),
    )
    if proc.returncode != 0:
        raise BackupError("Geri yükleme başarısız (işlem geri alındı): " + _tail(proc.stderr))


async def recent(settings: Settings, db_session: Any, limit: int = 30) -> list[dict[str, Any]]:
    rows = (
        await db_session.execute(select(Backup).order_by(Backup.created_at.desc()).limit(limit))
    ).scalars()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "file_name": r.file_name,
            "size_bytes": r.size_bytes,
            "sha256": r.sha256,
            "status": r.status,
            "duration_ms": r.duration_ms,
            "error": r.error,
            "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            "verify_ok": r.verify_ok,
            "verify": r.verify,
            "trigger": r.trigger,
        }
        for r in rows
    ]


__all__ = ["BackupError", "create", "recent", "restore", "verify"]
