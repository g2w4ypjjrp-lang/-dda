"""MI_SECRET_KEK döndürme: MFA sırları yeni anahtara taşınır, eski anahtar artık işe yaramaz."""

from __future__ import annotations

import base64
from typing import Any

import psycopg
import pytest

from conftest import KEK, Clock, enable_mfa, login, make_settings, new_client, signup_and_login
from mi_api.cli import rotate_kek

NEW = base64.b64encode(b"n" * 32).decode()


async def _mfa_login(app: Any, email: str, code: str) -> int:
    async with new_client(app) as c:
        await login(c, email)
        return (await c.post("/v1/auth/login/mfa", json={"code": code})).status_code


async def test_rotate_kek_moves_mfa_secrets(
    app_factory: Any, dsn: str, sql: psycopg.Connection[Any], clock: Clock, monkeypatch: Any
) -> None:
    old_app = app_factory()
    totps = {}
    for email in ("bir@ornek.com", "iki@ornek.com"):
        async with new_client(old_app) as c:
            await signup_and_login(c, email)
            totps[email], _ = await enable_mfa(c, clock)
    before = sql.execute("SELECT id, mfa_secret_enc FROM users ORDER BY id").fetchall()

    settings = make_settings(dsn)
    monkeypatch.setenv("MI_NEW_SECRET_KEK", NEW)
    # Kuru çalıştırma: hiçbir şey yazmaz.
    dry = await rotate_kek(settings, dry_run=True)
    assert dry == {"secrets": 2, "rotated": 2, "already_rotated": 0, "dry_run": 1}
    assert sql.execute("SELECT id, mfa_secret_enc FROM users ORDER BY id").fetchall() == before

    result = await rotate_kek(settings, dry_run=False)
    assert result == {"secrets": 2, "rotated": 2, "already_rotated": 0, "dry_run": 0}
    after = sql.execute("SELECT id, mfa_secret_enc FROM users ORDER BY id").fetchall()
    assert all(a[1] != b[1] for a, b in zip(after, before, strict=True))
    # Tekrar çalıştırmak güvenli: zaten taşınmış sırlar atlanır.
    again = await rotate_kek(settings, dry_run=False)
    assert again == {"secrets": 2, "rotated": 0, "already_rotated": 2, "dry_run": 0}
    rows = sql.execute(
        "SELECT details FROM audit_log WHERE action = 'system.kek_rotated' ORDER BY id"
    ).fetchall()
    assert [r[0] for r in rows] == [
        {"rotated": 2, "already_rotated": 0},
        {"rotated": 0, "already_rotated": 2},
    ]

    # Yeni anahtarla çalışan uygulamada MFA girişi çalışır; eski anahtarla çalışan çalışmaz.
    new_app = app_factory(secret_kek=NEW)
    assert await _mfa_login(new_app, "bir@ornek.com", totps["bir@ornek.com"].code()) == 200
    # Eski anahtarla kalmış süreç: 500 değil, nedeni belli 503 (ve kod "yanlış" sayılmaz).
    stale_app = app_factory(secret_kek=KEK)
    assert await _mfa_login(stale_app, "iki@ornek.com", totps["iki@ornek.com"].code()) == 503


async def test_rotate_kek_refuses_bad_input_without_changes(
    app: Any, dsn: str, sql: psycopg.Connection[Any], clock: Clock, monkeypatch: Any
) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "uc@ornek.com")
        await enable_mfa(c, clock)
    before = sql.execute("SELECT mfa_secret_enc FROM users").fetchall()
    settings = make_settings(dsn)

    monkeypatch.delenv("MI_NEW_SECRET_KEK", raising=False)
    with pytest.raises(SystemExit, match="MI_NEW_SECRET_KEK"):
        await rotate_kek(settings, dry_run=False)
    monkeypatch.setenv("MI_NEW_SECRET_KEK", base64.b64encode(b"kisa").decode())
    with pytest.raises(SystemExit, match="32 bayt"):
        await rotate_kek(settings, dry_run=False)
    monkeypatch.setenv("MI_NEW_SECRET_KEK", KEK)
    with pytest.raises(SystemExit, match="aynı"):
        await rotate_kek(settings, dry_run=False)
    # Yanlış "eski" anahtar: hiçbir sır açılamaz → tek satır bile değişmez.
    monkeypatch.setenv("MI_NEW_SECRET_KEK", NEW)
    wrong = make_settings(dsn, secret_kek=base64.b64encode(b"w" * 32).decode())
    with pytest.raises(SystemExit, match="hiçbir şey"):
        await rotate_kek(wrong, dry_run=False)
    assert sql.execute("SELECT mfa_secret_enc FROM users").fetchall() == before
    assert sql.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'system.kek_rotated'"
    ).fetchone() == (0,)
