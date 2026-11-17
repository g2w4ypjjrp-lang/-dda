"""Veritabanı düzeyindeki güvenceler (savunma derinliği)."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from sqlalchemy import create_engine, inspect

from mi_api import rbac
from mi_api.migrate import head_revision, sync_url
from mi_api.models import Base


def test_migration_at_head(sql: Any) -> None:
    assert sql.execute("SELECT version_num FROM alembic_version").fetchone()[0] == head_revision()


def test_models_match_migrated_schema(dsn: str) -> None:
    engine = create_engine(sync_url(dsn))
    try:
        inspector = inspect(engine)
        for table in Base.metadata.sorted_tables:
            db_cols = {c["name"] for c in inspector.get_columns(table.name)}
            assert db_cols == {c.name for c in table.columns}, table.name
    finally:
        engine.dispose()


def test_rbac_catalog_matches_database(sql: Any) -> None:
    roles = {r[0]: r[1] for r in sql.execute("SELECT code, description FROM roles")}
    assert roles == rbac.ROLES
    perms = {
        r[0]: (r[1], r[2])
        for r in sql.execute("SELECT code, description, sensitive FROM permissions")
    }
    assert perms == {k: (v, k in rbac.SENSITIVE) for k, v in rbac.PERMISSIONS.items()}
    matrix: dict[str, set[str]] = {}
    for role, perm in sql.execute("SELECT role_code, permission_code FROM role_permissions"):
        matrix.setdefault(role, set()).add(perm)
    assert matrix == {k: set(v) for k, v in rbac.ROLE_PERMISSIONS.items()}
    assert set(rbac.PERMISSIONS) >= rbac.SENSITIVE


def _insert_user(sql: Any, email: str, *, status: str = "active") -> str:
    return str(
        sql.execute(
            "INSERT INTO users (id, email, display_name, status, deleted_at) VALUES (gen_random_uuid(), %s, 'X', %s,"
            " CASE WHEN %s = 'deleted' THEN now() END) RETURNING id",
            (email, status, status),
        ).fetchone()[0]
    )


def test_password_must_be_argon2id(sql: Any) -> None:
    uid = _insert_user(sql, "a@ornek.com")
    with pytest.raises(psycopg.errors.CheckViolation):
        sql.execute("UPDATE users SET password_hash = 'md5$abc' WHERE id = %s", (uid,))


def test_email_must_be_lowercase(sql: Any) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_user(sql, "Buyuk@Ornek.com")


def test_mfa_enabled_requires_secret(sql: Any) -> None:
    uid = _insert_user(sql, "a@ornek.com")
    with pytest.raises(psycopg.errors.CheckViolation):
        sql.execute("UPDATE users SET mfa_enabled_at = now() WHERE id = %s", (uid,))


def test_last_super_admin_protected(sql: Any) -> None:
    first = _insert_user(sql, "kok@ornek.com")
    second = _insert_user(sql, "kok2@ornek.com")
    sql.execute(
        "INSERT INTO user_roles (user_id, role_code) VALUES (%s, 'SUPER_ADMIN'), (%s, 'SUPER_ADMIN')",
        (first, second),
    )
    sql.execute("DELETE FROM user_roles WHERE user_id = %s", (first,))
    with pytest.raises(psycopg.errors.CheckViolation):
        sql.execute("DELETE FROM user_roles WHERE user_id = %s", (second,))


def _audit(sql: Any, action: str) -> None:
    sql.execute(
        "INSERT INTO audit_log (actor_type, action, details, prev_hash, hash)"
        " VALUES ('system', %s, '{}', '\\x', '\\x')",
        (action,),
    )


def test_audit_log_append_only_and_chained(sql: Any) -> None:
    for i in range(3):
        _audit(sql, f"test.event_{'abc'[i]}")
    rows = sql.execute("SELECT prev_hash, hash FROM audit_log ORDER BY id").fetchall()
    assert bytes(rows[0][0]) == b"\x00" * 32
    assert bytes(rows[1][0]) == bytes(rows[0][1]) and bytes(rows[2][0]) == bytes(rows[1][1])
    assert sql.execute("SELECT audit_log_verify()").fetchone()[0] is None
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("UPDATE audit_log SET action = 'test.changed'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("DELETE FROM audit_log")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("TRUNCATE audit_log")


def test_audit_tampering_detected_even_with_triggers_disabled(sql: Any) -> None:
    for name in ("test.one", "test.two", "test.three"):
        _audit(sql, name)
    second = sql.execute("SELECT id FROM audit_log ORDER BY id OFFSET 1 LIMIT 1").fetchone()[0]
    # Süper kullanıcı tetikleyiciyi kapatıp kaydı değiştirse bile zincir bunu yakalar.
    sql.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_log_immutable")
    sql.execute("UPDATE audit_log SET details = '{\"x\": 1}' WHERE id = %s", (second,))
    sql.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_log_immutable")
    assert sql.execute("SELECT audit_log_verify()").fetchone()[0] == second


def test_audit_action_format(sql: Any) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _audit(sql, "Gecersiz Eylem")
