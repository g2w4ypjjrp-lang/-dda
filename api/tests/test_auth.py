"""Kullanıcı kimlik doğrulama uçtan uca testleri (gerçek PostgreSQL)."""

from __future__ import annotations

from typing import Any

import httpx
import psycopg
import pytest

from conftest import (
    PASSWORD,
    Clock,
    enable_mfa,
    login,
    new_client,
    outbox_token,
    register,
    signup_and_login,
)


def audit_actions(sql: psycopg.Connection[Any]) -> list[str]:
    return [r[0] for r in sql.execute("SELECT action FROM audit_log ORDER BY id")]


async def test_register_verify_login_me_logout(client: httpx.AsyncClient, sql: Any) -> None:
    await register(client, "Ayse@Ornek.com")
    row = sql.execute("SELECT email, password_hash, email_verified_at FROM users").fetchone()
    assert row[0] == "ayse@ornek.com"
    assert row[1].startswith("$argon2id$")
    assert row[2] is None

    token = outbox_token(sql, "ayse@ornek.com", "verify_email")
    r = await client.post("/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 200
    # Belirteç tek kullanımlık.
    r = await client.post("/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 400 and r.json()["code"] == "invalid_token"

    r = await login(client, "ayse@ornek.com")
    assert r.status_code == 200
    assert r.json()["user"]["email_verified"] is True
    assert "mi_session" in r.cookies
    me = await client.get("/v1/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "ayse@ornek.com"
    assert "password_hash" not in me.text

    assert (await client.post("/v1/auth/logout")).status_code == 200
    assert (await client.get("/v1/auth/me")).status_code == 401
    assert audit_actions(sql) == [
        "user.registered", "user.email_verified", "auth.login", "auth.logout",
    ]  # fmt: skip


async def test_tokens_are_stored_only_as_digests(client: httpx.AsyncClient, sql: Any) -> None:
    await signup_and_login(client, "ozet@ornek.com")
    session_token = client.cookies["mi_session"]
    stored = sql.execute("SELECT token_digest FROM user_sessions").fetchone()[0]
    assert session_token.encode() not in bytes(stored)
    assert len(bytes(stored)) == 32


async def test_register_does_not_reveal_existing_email(client: httpx.AsyncClient, sql: Any) -> None:
    await register(client, "var@ornek.com")
    r = await client.post(
        "/v1/auth/register",
        json={
            "email": "var@ornek.com",
            "password": "Baska-Parola-99",
            "display_name": "X",
            "accept_terms": True,
        },
    )
    assert r.status_code == 202
    assert (
        r.json()
        == (
            await client.post(
                "/v1/auth/register",
                json={
                    "email": "yok@ornek.com",
                    "password": "Baska-Parola-99",
                    "display_name": "Y",
                    "accept_terms": True,
                },
            )
        ).json()
    )
    templates = [
        r[0]
        for r in sql.execute(
            "SELECT template FROM email_outbox WHERE to_address='var@ornek.com' ORDER BY id"
        )
    ]
    assert templates == ["verify_email", "account_exists"]
    # Mevcut hesabın parolası değişmedi.
    assert (await login(client, "var@ornek.com")).status_code == 200


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("kisa", "weak_password"),
        ("1234567890", "weak_password"),
        ("zeynep-uzun-parola", "weak_password"),
    ],
)
async def test_weak_passwords_rejected(client: httpx.AsyncClient, password: str, code: str) -> None:
    r = await client.post(
        "/v1/auth/register",
        json={
            "email": "zeynep@ornek.com",
            "password": password,
            "display_name": "Z",
            "accept_terms": True,
        },
    )
    assert r.status_code == 422 and r.json()["code"] == code


async def test_terms_must_be_accepted(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/v1/auth/register",
        json={
            "email": "a@ornek.com",
            "password": PASSWORD,
            "display_name": "A",
            "accept_terms": False,
        },
    )
    assert r.json()["code"] == "terms_required"


async def test_failed_login_is_audited_and_generic(client: httpx.AsyncClient, sql: Any) -> None:
    await register(client, "mehmet@ornek.com")
    wrong = await login(client, "mehmet@ornek.com", "Yanlis-Parola-1")
    missing = await login(client, "hayalet@ornek.com", "Yanlis-Parola-1")
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    # Hata yanıtına rağmen denetim kaydı kalıcı.
    assert audit_actions(sql).count("auth.login_failed") == 2


async def test_login_rate_limited_per_email(client: httpx.AsyncClient) -> None:
    await register(client, "hiz@ornek.com")
    statuses = [
        (await login(client, "hiz@ornek.com", "Yanlis-Parola-1")).status_code for _ in range(11)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    # Doğru parola da sınır dolunca reddedilir (kaba kuvvet koruması).
    assert (await login(client, "hiz@ornek.com")).status_code == 429


async def test_suspended_user_cannot_login(client: httpx.AsyncClient, sql: Any) -> None:
    await register(client, "askida@ornek.com")
    sql.execute("UPDATE users SET status='suspended' WHERE email='askida@ornek.com'")
    r = await login(client, "askida@ornek.com")
    assert r.status_code == 403 and r.json()["code"] == "account_suspended"


async def test_password_reset_flow_revokes_sessions(app: Any, sql: Any, clock: Clock) -> None:
    async with new_client(app) as a, new_client(app) as b:
        await signup_and_login(a, "sifre@ornek.com")
        assert (await login(b, "sifre@ornek.com")).status_code == 200

        r = await b.post("/v1/auth/password/forgot", json={"email": "sifre@ornek.com"})
        assert r.status_code == 202
        r2 = await b.post("/v1/auth/password/forgot", json={"email": "olmayan@ornek.com"})
        assert r.json() == r2.json()
        token = outbox_token(sql, "sifre@ornek.com", "password_reset")

        r = await b.post(
            "/v1/auth/password/reset", json={"token": token, "password": "Yeni-Parola-2026"}
        )
        assert r.status_code == 200
        # Tüm oturumlar kapandı; eski parola geçersiz, yenisi geçerli.
        assert (await a.get("/v1/auth/me")).status_code == 401
        assert (await b.get("/v1/auth/me")).status_code == 401
        assert (await login(b, "sifre@ornek.com")).status_code == 401
        assert (await login(b, "sifre@ornek.com", "Yeni-Parola-2026")).status_code == 200
        r = await b.post(
            "/v1/auth/password/reset", json={"token": token, "password": "Baska-Parola-2026"}
        )
        assert r.status_code == 400


async def test_password_reset_token_expires(
    client: httpx.AsyncClient, sql: Any, clock: Clock
) -> None:
    await register(client, "sure@ornek.com")
    await client.post("/v1/auth/password/forgot", json={"email": "sure@ornek.com"})
    token = outbox_token(sql, "sure@ornek.com", "password_reset")
    clock.advance(hours=1, seconds=1)
    r = await client.post(
        "/v1/auth/password/reset", json={"token": token, "password": "Yeni-Parola-2026"}
    )
    assert r.status_code == 400


async def test_newer_reset_token_invalidates_older(client: httpx.AsyncClient, sql: Any) -> None:
    await register(client, "iki@ornek.com")
    await client.post("/v1/auth/password/forgot", json={"email": "iki@ornek.com"})
    first = outbox_token(sql, "iki@ornek.com", "password_reset")
    await client.post("/v1/auth/password/forgot", json={"email": "iki@ornek.com"})
    second = outbox_token(sql, "iki@ornek.com", "password_reset")
    assert (
        await client.post(
            "/v1/auth/password/reset", json={"token": first, "password": "Yeni-Parola-2026"}
        )
    ).status_code == 400
    assert (
        await client.post(
            "/v1/auth/password/reset", json={"token": second, "password": "Yeni-Parola-2026"}
        )
    ).status_code == 200


async def test_change_password_keeps_current_session_only(app: Any) -> None:
    async with new_client(app) as a, new_client(app) as b:
        await signup_and_login(a, "degis@ornek.com")
        await login(b, "degis@ornek.com")
        r = await a.post(
            "/v1/auth/password/change",
            json={"current_password": PASSWORD, "new_password": "Yepyeni-Parola-1"},
        )
        assert r.status_code == 200
        assert (await a.get("/v1/auth/me")).status_code == 200
        assert (await b.get("/v1/auth/me")).status_code == 401


async def test_session_expires(client: httpx.AsyncClient, clock: Clock) -> None:
    await signup_and_login(client, "eski@ornek.com")
    clock.advance(days=30, seconds=1)
    assert (await client.get("/v1/auth/me")).status_code == 401


async def test_mfa_two_step_login(app: Any, sql: Any, clock: Clock) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "mfa@ornek.com")
        totp, codes = await enable_mfa(c, clock)
        assert len(codes) == 10 and len(set(codes)) == 10
        secret_enc = sql.execute("SELECT mfa_secret_enc FROM users").fetchone()[0]
        assert totp.secret not in bytes(secret_enc)  # TOTP sırrı şifreli saklanır
        await c.post("/v1/auth/logout")

        r = await login(c, "mfa@ornek.com")
        assert r.json() == {"status": "mfa_required", "mfa_required": True}
        # İkinci adım tamamlanmadan oturum kullanılamaz.
        me = await c.get("/v1/auth/me")
        assert me.status_code == 401 and me.json()["code"] == "mfa_required"
        assert (await c.post("/v1/auth/login/mfa", json={"code": "000000"})).status_code == 401
        code = totp.code()
        assert (await c.post("/v1/auth/login/mfa", json={"code": code})).status_code == 200
        assert (await c.get("/v1/auth/me")).json()["mfa_enabled"] is True

        # Aynı kod (aynı zaman adımı) ikinci kez kabul edilmez.
        await c.post("/v1/auth/logout")
        await login(c, "mfa@ornek.com")
        assert (await c.post("/v1/auth/login/mfa", json={"code": code})).status_code == 401


async def test_mfa_recovery_code_single_use(app: Any, clock: Clock) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "kurtar@ornek.com")
        _, codes = await enable_mfa(c, clock)
        for expected in (200, 401):
            await c.post("/v1/auth/logout")
            await login(c, "kurtar@ornek.com")
            r = await c.post("/v1/auth/login/mfa", json={"code": codes[0].lower()})
            assert r.status_code == expected


async def test_mfa_pending_session_locks_after_attempts(app: Any, sql: Any, clock: Clock) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "kilit@ornek.com")
        totp, _ = await enable_mfa(c, clock)
        await c.post("/v1/auth/logout")
        await login(c, "kilit@ornek.com")
        for _ in range(5):
            assert (await c.post("/v1/auth/login/mfa", json={"code": "111111"})).json()[
                "code"
            ] == "invalid_code"
        r = await c.post("/v1/auth/login/mfa", json={"code": totp.code()})
        assert r.json()["code"] == "mfa_locked"
        assert (await c.post("/v1/auth/login/mfa", json={"code": totp.code()})).status_code == 401
        assert (
            sql.execute("SELECT count(*) FROM audit_log WHERE action='auth.mfa_failed'").fetchone()[
                0
            ]
            == 5
        )


async def test_mfa_pending_session_expires(app: Any, clock: Clock) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "bekle@ornek.com")
        totp, _ = await enable_mfa(c, clock)
        await c.post("/v1/auth/logout")
        await login(c, "bekle@ornek.com")
        clock.advance(minutes=6)
        assert (await c.post("/v1/auth/login/mfa", json={"code": totp.code()})).status_code == 401


async def test_mfa_disable_requires_password_and_code(app: Any, clock: Clock) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "kapat@ornek.com")
        totp, _ = await enable_mfa(c, clock)
        r = await c.post(
            "/v1/auth/mfa/disable", json={"password": "Yanlis-Parola-1", "code": totp.code()}
        )
        assert r.status_code == 401
        r = await c.post("/v1/auth/mfa/disable", json={"password": PASSWORD, "code": totp.code()})
        assert r.status_code == 200
        assert (await c.get("/v1/auth/me")).json()["mfa_enabled"] is False


async def test_mfa_unavailable_without_kek(app_factory: Any) -> None:
    async with new_client(app_factory(secret_kek=None)) as c:
        await signup_and_login(c, "kek@ornek.com")
        r = await c.post("/v1/auth/mfa/setup")
        assert r.status_code == 503 and r.json()["code"] == "mfa_unavailable"


async def test_sessions_list_and_revoke(app: Any) -> None:
    async with new_client(app) as a, new_client(app) as b:
        await signup_and_login(a, "oturum@ornek.com")
        await login(b, "oturum@ornek.com")
        items = (await a.get("/v1/auth/sessions")).json()["items"]
        assert len(items) == 2
        other = next(i for i in items if not i["current"])
        assert (await a.post(f"/v1/auth/sessions/{other['id']}/revoke")).status_code == 200
        assert (await b.get("/v1/auth/me")).status_code == 401


async def test_cannot_revoke_someone_elses_session(app: Any, sql: Any) -> None:
    async with new_client(app) as a, new_client(app) as b:
        await signup_and_login(a, "bir@ornek.com")
        await signup_and_login(b, "iki@ornek.com")
        b_session = sql.execute(
            "SELECT s.id FROM user_sessions s JOIN users u ON u.id=s.user_id WHERE u.email='iki@ornek.com'"
        ).fetchone()[0]
        assert (await a.post(f"/v1/auth/sessions/{b_session}/revoke")).status_code == 404
        assert (await b.get("/v1/auth/me")).status_code == 200


async def test_delete_account_anonymizes(client: httpx.AsyncClient, sql: Any) -> None:
    await signup_and_login(client, "sil@ornek.com")
    r = await client.post("/v1/auth/delete-account", json={"password": PASSWORD})
    assert r.status_code == 200
    row = sql.execute("SELECT email, display_name, password_hash, status FROM users").fetchone()
    assert row[0].endswith("@deleted.invalid") and row[1] == "Silinmiş kullanıcı"
    assert row[2] is None and row[3] == "deleted"
    assert (
        sql.execute(
            "SELECT count(*) FROM email_outbox WHERE status='pending' AND to_address='sil@ornek.com'"
        ).fetchone()[0]
        == 0
    )
    assert (await client.get("/v1/auth/me")).status_code == 401
    assert (await login(client, "sil@ornek.com")).status_code == 401
    # Aynı e-postayla yeniden kayıt olunabilir.
    await signup_and_login(client, "sil@ornek.com")


async def test_csrf_foreign_origin_rejected(app: Any) -> None:
    async with new_client(app, origin="https://kotu-site.example") as evil:
        r = await evil.post("/v1/auth/login", json={"email": "a@b.co", "password": "x"})
        assert r.status_code == 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as no_origin:
        r = await no_origin.post("/v1/auth/logout")
        assert r.status_code == 403
