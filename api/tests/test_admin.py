"""Yönetim API'si: yönetici oturumu, RBAC, yeniden doğrulama, kullanıcı ve rol yönetimi."""

from __future__ import annotations

from typing import Any

import pytest

from conftest import (
    PASSWORD,
    Clock,
    enable_mfa,
    grant_role,
    make_staff,
    new_client,
    signup_and_login,
    use,
)


async def test_admin_login_requires_staff_role(app: Any, clock: Clock) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "musteri@ornek.com")
        totp, _ = await enable_mfa(c, clock)
        r = await c.post(
            "/admin/v1/auth/login",
            json={"email": "musteri@ornek.com", "password": PASSWORD, "code": totp.code()},
        )
        assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
        # Müşteri oturum çerezi yönetim API'sini açmaz.
        assert (await c.get("/admin/v1/me")).status_code == 401


async def test_staff_without_mfa_must_enroll(app: Any, sql: Any) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "yeni.yonetici@ornek.com")
        grant_role(sql, "yeni.yonetici@ornek.com", "SUPPORT")
        r = await c.post(
            "/admin/v1/auth/login",
            json={"email": "yeni.yonetici@ornek.com", "password": PASSWORD, "code": "123456"},
        )
        assert r.status_code == 403 and r.json()["code"] == "mfa_enrollment_required"


async def test_admin_login_wrong_code(app: Any, sql: Any, clock: Clock) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "kod@ornek.com")
        await enable_mfa(c, clock)
        grant_role(sql, "kod@ornek.com", "ADMIN")
        r = await c.post(
            "/admin/v1/auth/login",
            json={"email": "kod@ornek.com", "password": PASSWORD, "code": "000000"},
        )
        assert r.status_code == 401
        assert (
            sql.execute(
                "SELECT details->>'reason' FROM audit_log WHERE action='admin.login_failed'"
            ).fetchone()[0]
            == "mfa"
        )


async def test_admin_me_lists_permissions(app: Any, sql: Any, clock: Clock) -> None:
    staff = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    async with use(staff.client) as c:
        me = (await c.get("/admin/v1/me")).json()
        assert me["roles"] == ["SUPPORT"]
        assert "users.read" in me["permissions"] and "audit.read" not in me["permissions"]
        assert me["reauth_fresh"] is True


@pytest.mark.parametrize(
    ("role", "path", "expected"),
    [
        ("SUPPORT", "/admin/v1/users", 200),
        ("SUPPORT", "/admin/v1/audit", 403),
        ("SUPPORT", "/admin/v1/roles", 403),
        ("ANALYST", "/admin/v1/users", 403),
        ("CONTENT_MANAGER", "/admin/v1/users", 403),
        ("FINANCE_MANAGER", "/admin/v1/users", 200),
        ("OPERATIONS_MANAGER", "/admin/v1/audit", 403),
        ("ADMIN", "/admin/v1/audit", 200),
        ("ADMIN", "/admin/v1/roles", 200),
        ("SUPER_ADMIN", "/admin/v1/audit/verify", 200),
    ],
)
async def test_permissions_enforced_in_backend(
    app: Any, sql: Any, clock: Clock, role: str, path: str, expected: int
) -> None:
    staff = await make_staff(app, sql, clock, "rol@ornek.com", role)
    async with use(staff.client) as c:
        assert (await c.get(path)).status_code == expected


async def test_sensitive_action_requires_fresh_reauth(app: Any, sql: Any, clock: Clock) -> None:
    staff = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with new_client(app) as u:
        await signup_and_login(u, "hedef@ornek.com")
    target = sql.execute("SELECT id FROM users WHERE email='hedef@ornek.com'").fetchone()[0]
    async with use(staff.client) as c:
        clock.advance(minutes=6)
        r = await c.post(f"/admin/v1/users/{target}/suspend", json={"reason": "Kötüye kullanım"})
        assert r.status_code == 403 and r.json()["code"] == "reauth_required"
        r = await c.post(
            "/admin/v1/auth/reauth", json={"password": "Yanlis-Parola-1", "code": staff.totp.code()}
        )
        assert r.status_code == 401
        r = await c.post(
            "/admin/v1/auth/reauth", json={"password": PASSWORD, "code": staff.totp.code()}
        )
        assert r.status_code == 200 and r.json()["reauth_fresh"] is True
        r = await c.post(f"/admin/v1/users/{target}/suspend", json={"reason": "Kötüye kullanım"})
        assert r.status_code == 200


async def test_suspend_revokes_sessions_and_activate(app: Any, sql: Any, clock: Clock) -> None:
    staff = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with new_client(app) as u, use(staff.client) as c:
        await signup_and_login(u, "hedef@ornek.com")
        target = sql.execute("SELECT id FROM users WHERE email='hedef@ornek.com'").fetchone()[0]
        assert (
            await c.post(f"/admin/v1/users/{target}/suspend", json={"reason": "İnceleme"})
        ).status_code == 200
        assert (await u.get("/v1/auth/me")).status_code == 401
        detail = (await c.get(f"/admin/v1/users/{target}")).json()
        assert detail["status"] == "suspended" and detail["suspended_reason"] == "İnceleme"
        assert "password" not in str(detail)
        assert (await c.post(f"/admin/v1/users/{target}/activate")).status_code == 200
        assert (await c.post(f"/admin/v1/users/{target}/activate")).status_code == 409


async def test_cannot_suspend_self_or_super_admin_as_admin(
    app: Any, sql: Any, clock: Clock
) -> None:
    root = await make_staff(app, sql, clock, "kok@ornek.com", "SUPER_ADMIN")
    staff = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    me = sql.execute("SELECT id FROM users WHERE email='admin@ornek.com'").fetchone()[0]
    root_id = sql.execute("SELECT id FROM users WHERE email='kok@ornek.com'").fetchone()[0]
    async with use(staff.client) as c, use(root.client):
        assert (await c.post(f"/admin/v1/users/{me}/suspend", json={"reason": "Deneme"})).json()[
            "code"
        ] == "self_action"
        assert (
            await c.post(f"/admin/v1/users/{root_id}/suspend", json={"reason": "Deneme"})
        ).status_code == 403


async def test_last_super_admin_cannot_be_suspended(app: Any, sql: Any, clock: Clock) -> None:
    root = await make_staff(app, sql, clock, "kok@ornek.com", "SUPER_ADMIN")
    other = await make_staff(app, sql, clock, "kok2@ornek.com", "SUPER_ADMIN")
    first = sql.execute("SELECT id FROM users WHERE email='kok@ornek.com'").fetchone()[0]
    second = sql.execute("SELECT id FROM users WHERE email='kok2@ornek.com'").fetchone()[0]
    async with use(root.client) as a, use(other.client) as b:
        assert (
            await b.post(f"/admin/v1/users/{first}/suspend", json={"reason": "Devir"})
        ).status_code == 200
        # Artık tek aktif SUPER_ADMIN 'second'; onu askıya alacak başka SUPER_ADMIN yok.
        assert (await a.get("/admin/v1/me")).status_code == 401
        assert (
            await b.post(f"/admin/v1/users/{second}/suspend", json={"reason": "Deneme"})
        ).json()["code"] == "self_action"


async def test_role_assignment(app: Any, sql: Any, clock: Clock) -> None:
    root = await make_staff(app, sql, clock, "kok@ornek.com", "SUPER_ADMIN")
    async with new_client(app) as u, use(root.client) as c:
        await signup_and_login(u, "analist@ornek.com")
        target = sql.execute("SELECT id FROM users WHERE email='analist@ornek.com'").fetchone()[0]
        r = await c.put(f"/admin/v1/users/{target}/roles", json={"roles": ["ANALYST"]})
        assert r.status_code == 409 and r.json()["code"] == "mfa_required"
        totp, _ = await enable_mfa(u, clock)
        assert (
            await c.put(f"/admin/v1/users/{target}/roles", json={"roles": ["NOPE"]})
        ).status_code == 422
        r = await c.put(f"/admin/v1/users/{target}/roles", json={"roles": ["ANALYST"]})
        assert r.status_code == 200 and r.json()["roles"] == ["ANALYST"]

        r = await u.post(
            "/admin/v1/auth/login",
            json={"email": "analist@ornek.com", "password": PASSWORD, "code": totp.code()},
        )
        assert r.status_code == 200 and "models.manage" in r.json()["permissions"]
        # Personel MFA'yı kapatamaz.
        r = await u.post("/v1/auth/mfa/disable", json={"password": PASSWORD, "code": totp.code()})
        assert r.json()["code"] == "mfa_required_for_staff"

        # Rol kaldırılınca açık yönetici oturumu kapanır.
        assert (
            await c.put(f"/admin/v1/users/{target}/roles", json={"roles": []})
        ).status_code == 200
        assert (await u.get("/admin/v1/me")).status_code == 401
        details = sql.execute(
            "SELECT details FROM audit_log WHERE action='admin.roles_changed' ORDER BY id"
        ).fetchall()
        assert details[0][0] == {"added": ["ANALYST"], "removed": []}
        assert details[1][0] == {"added": [], "removed": ["ANALYST"]}


async def test_admin_cannot_assign_roles(app: Any, sql: Any, clock: Clock) -> None:
    staff = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    target = sql.execute("SELECT id FROM users WHERE email='admin@ornek.com'").fetchone()[0]
    async with use(staff.client) as c:
        assert (
            await c.put(f"/admin/v1/users/{target}/roles", json={"roles": ["SUPER_ADMIN"]})
        ).status_code == 403


async def test_super_admin_cannot_change_own_roles(app: Any, sql: Any, clock: Clock) -> None:
    root = await make_staff(app, sql, clock, "kok@ornek.com", "SUPER_ADMIN")
    me = sql.execute("SELECT id FROM users WHERE email='kok@ornek.com'").fetchone()[0]
    async with use(root.client) as c:
        r = await c.put(f"/admin/v1/users/{me}/roles", json={"roles": []})
        assert r.json()["code"] == "self_action"


async def test_users_list_search_filter_paginate(app: Any, sql: Any, clock: Clock) -> None:
    staff = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    async with new_client(app) as u:
        for i in range(5):
            await signup_and_login(u, f"oyuncu{i}@ornek.com")
    sql.execute("UPDATE users SET status='suspended' WHERE email='oyuncu3@ornek.com'")
    async with use(staff.client) as c:
        page = (await c.get("/admin/v1/users", params={"q": "oyuncu", "page_size": 2})).json()
        assert page["total"] == 5 and len(page["items"]) == 2
        assert (await c.get("/admin/v1/users", params={"status": "suspended"})).json()["total"] == 1
        support = (await c.get("/admin/v1/users", params={"role": "SUPPORT"})).json()
        assert [i["email"] for i in support["items"]] == ["destek@ornek.com"]
        # LIKE joker karakterleri kaçışlanır.
        assert (await c.get("/admin/v1/users", params={"q": "%"})).json()["total"] == 0


async def test_roles_matrix_and_audit_endpoints(app: Any, sql: Any, clock: Clock) -> None:
    root = await make_staff(app, sql, clock, "kok@ornek.com", "SUPER_ADMIN")
    async with use(root.client) as c:
        roles = (await c.get("/admin/v1/roles")).json()
        by_code = {r["code"]: r for r in roles["roles"]}
        assert set(by_code) == {
            "SUPER_ADMIN",
            "ADMIN",
            "SUPPORT",
            "ANALYST",
            "FINANCE_MANAGER",
            "OPERATIONS_MANAGER",
            "CONTENT_MANAGER",
        }
        assert by_code["SUPER_ADMIN"]["member_count"] == 1
        items = (await c.get("/admin/v1/audit", params={"action": "admin."})).json()["items"]
        assert items[0]["action"] == "admin.login"
        verify = (await c.get("/admin/v1/audit/verify")).json()
        assert verify["intact"] is True and verify["entries"] > 3


async def test_admin_session_expires(app: Any, sql: Any, clock: Clock) -> None:
    staff = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with use(staff.client) as c:
        clock.advance(hours=8, seconds=1)
        assert (await c.get("/admin/v1/me")).status_code == 401


async def test_admin_origin_enforced(app_factory: Any, sql: Any, clock: Clock) -> None:
    app = app_factory(admin_origins=["https://admin.ornek.com"])
    async with new_client(app) as c:
        r = await c.post(
            "/admin/v1/auth/login",
            json={"email": "a@ornek.com", "password": PASSWORD, "code": "123456"},
        )
        assert r.status_code == 403
    async with new_client(app, origin="https://admin.ornek.com") as c:
        r = await c.post(
            "/admin/v1/auth/login",
            json={"email": "a@ornek.com", "password": PASSWORD, "code": "123456"},
        )
        assert r.status_code == 401
