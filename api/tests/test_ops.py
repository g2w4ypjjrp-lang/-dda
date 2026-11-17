"""Faz 9: Command Center, System Health, Action Center, sipariş inceleme, bayraklar, güvenlik."""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any

import psycopg

from conftest import KEK, Clock, make_staff, member, new_client, signup_and_login, use
from test_billing import PEPPER, set_price, sim_order, verify


async def test_overview_sections_follow_permissions(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    async with use(admin.client) as a, use(support.client) as s:
        full = (await a.get("/admin/v1/overview")).json()
        assert {"business", "users", "football", "ai", "coupons", "virtual"} <= set(full)
        # Gerçek kayıt yoksa uydurma değer yok.
        b = full["business"]
        assert b["revenue"] is None and b["mrr_minor"] is None and b["revenue_today_minor"] is None
        assert b["costs"] == {"api": None, "server": None}
        assert full["users"]["total"] == 2 and full["users"]["plans"]["PRO"] == 0
        assert full["ai"]["settled_30d"]["n"] == 0 and full["ai"]["settled_30d"]["log_loss"] is None
        assert full["virtual"]["simulated_roi"] is None
        limited = (await s.get("/admin/v1/overview")).json()
        assert "users" in limited and "business" not in limited and "ai" not in limited


async def test_health_metrics_and_errors(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    await app.state.metrics.record("GET", "/v1/ornek", 500, 12.5, "abcd1234")
    async with use(admin.client) as a, use(support.client) as s:
        assert (await s.get("/admin/v1/health")).status_code == 403
        h = (await a.get("/admin/v1/health")).json()
        comp = h["components"]
        assert (
            comp["database"]["status"] == "ok"
            and comp["database"]["schema"] == comp["database"]["schema_head"]
        )
        assert comp["football_api"]["status"] == "not_configured"
        assert comp["payment_api"]["status"] == "not_configured"
        assert comp["workers"]["status"] == "unknown"  # kalp atışı yok: uydurma "çalışıyor" yok
        assert (
            comp["backend"]["window"]["requests"] >= 1
            and comp["backend"]["window"]["errors_5xx"] >= 1
        )
        assert h["host"]["disk"]["used_pct"] > 0 and h["costs"]["api"] is None
        errs = (await a.get("/admin/v1/health/errors")).json()["items"]
        assert errs[0]["path"] == "/v1/ornek" and errs[0]["request_id"] == "abcd1234"
        assert set(errs[0]) == {
            "ts",
            "method",
            "path",
            "status",
            "request_id",
        }  # gövde/kullanıcı bilgisi yok
        actions = (await a.get("/admin/v1/actions")).json()["items"]
        assert any(i["category"] == "errors" and i["severity"] == "critical" for i in actions)


async def test_action_center_ack_and_order_review(
    app_factory: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    app = app_factory(payment_provider="simulator", license_pepper=PEPPER)
    set_price(sql, "PRO", "monthly", 19900)
    async with new_client(app) as c:
        await signup_and_login(c, "musteri@ornek.com")
        verify(sql, "musteri@ornek.com")
        order_id, _ = await sim_order(c)
    number = sql.execute("SELECT id FROM orders").fetchone()[0]
    sql.execute(
        "UPDATE orders SET status='review', provider_payment_id='sim_pay_x', note='Tutar uyuşmazlığı' WHERE id=%s",
        (number,),
    )

    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    finance = await make_staff(app, sql, clock, "finans@ornek.com", "FINANCE_MANAGER")
    async with use(admin.client) as a, use(finance.client) as f:
        items = (await a.get("/admin/v1/actions")).json()["items"]
        keys = {i["key"] for i in items}
        assert {f"order_review:{number}", "football_provider:none", "models:no_champion"} <= keys
        # Yetki süzgeci: finans rolü model/veri uyarılarını görmez.
        fkeys = {i["key"] for i in (await f.get("/admin/v1/actions")).json()["items"]}
        assert f"order_review:{number}" in fkeys and "models:no_champion" not in fkeys

        r = await a.post(
            "/admin/v1/actions/ack", json={"key": "models:no_champion", "note": "Eğitim planlandı"}
        )
        assert r.status_code == 200
        keys = {i["key"] for i in (await a.get("/admin/v1/actions")).json()["items"]}
        assert "models:no_champion" not in keys
        acked = (await a.get("/admin/v1/actions", params={"include_acked": True})).json()["items"]
        assert (
            next(i for i in acked if i["key"] == "models:no_champion")["acked"]["note"]
            == "Eğitim planlandı"
        )
        assert (await a.post("/admin/v1/actions/ack", json={"key": "yok:1"})).status_code == 404

        body = {"action": "approve", "note": "Banka dekontu doğrulandı", "confirm": True}
        assert (
            await a.post(f"/admin/v1/billing/orders/{number}/resolve", json=body)
        ).status_code == 403  # ADMIN'de finance.refund yok
        r = await f.post(f"/admin/v1/billing/orders/{number}/resolve", json=body)
        assert r.status_code == 200 and r.json()["status"] == "paid", r.text
        assert sql.execute("SELECT plan_code, source FROM subscriptions").fetchone() == (
            "PRO",
            "payment",
        )
        assert (
            await f.post(f"/admin/v1/billing/orders/{number}/resolve", json=body)
        ).status_code == 409
        keys = {i["key"] for i in (await f.get("/admin/v1/actions")).json()["items"]}
        assert f"order_review:{number}" not in keys
    actions = [
        r[0]
        for r in sql.execute(
            "SELECT action FROM audit_log WHERE action IN ('admin.action_acked','billing.review_approve')"
        )
    ]
    assert sorted(actions) == ["admin.action_acked", "billing.review_approve"]
    assert order_id


async def test_feature_flags_are_enforced(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, Any]
) -> None:
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    async with use(admin.client) as a:
        flags = {f["key"]: f for f in (await a.get("/admin/v1/flags")).json()["items"]}
        assert flags["registration_open"]["enabled"] is True and len(flags) == 5
        assert (
            await a.put("/admin/v1/flags/registration_open", json={"enabled": False})
        ).status_code == 200
        assert (
            await a.put(
                "/admin/v1/flags/coupons_enabled", json={"enabled": False, "message": "Bakımdayız"}
            )
        ).status_code == 200
        r = await a.put("/admin/v1/flags/maintenance_notice", json={"enabled": True})
        assert r.status_code == 422
        assert (
            await a.put(
                "/admin/v1/flags/maintenance_notice",
                json={"enabled": True, "message": "Bu gece 02:00 bakım"},
            )
        ).status_code == 200
        assert (await a.put("/admin/v1/flags/yok", json={"enabled": True})).status_code == 404
    async with new_client(app) as c:
        r = await c.post(
            "/v1/auth/register",
            json={
                "email": "yeni@ornek.com",
                "password": "Gizli-Parola-2026!",
                "display_name": "Yeni",
                "accept_terms": True,
            },
        )
        assert r.status_code == 503 and r.json()["code"] == "feature_disabled"
        assert (await c.get("/v1/notice")).json() == {"message": "Bu gece 02:00 bakım"}
    sql.execute("UPDATE feature_flags SET enabled = true WHERE key = 'registration_open'")
    async with new_client(app) as c:
        await member(c, sql, "pro@ornek.com", plan="PRO")
        r = await c.post("/v1/coupons/generate", json={"date": "2026-11-20", "size": 2})
        assert r.status_code == 503 and r.json()["detail"] == "Bakımdayız"
    assert (
        sql.execute("SELECT count(*) FROM audit_log WHERE action='admin.flag_changed'").fetchone()[
            0
        ]
        == 3
    )


async def test_security_center_settings_and_roles(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    async with new_client(app) as c:
        await signup_and_login(c, "kurban@ornek.com")
        for _ in range(3):
            await c.post(
                "/v1/auth/login",
                json={"email": "kurban@ornek.com", "password": "yanlis-parola-123"},
            )
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    analyst = await make_staff(app, sql, clock, "analist@ornek.com", "ANALYST")
    async with use(admin.client) as a, use(analyst.client) as an:
        sec = (await a.get("/admin/v1/security")).json()
        assert sec["counts"]["auth.login_failed"] == 3
        assert sec["staff"]["total"] == 2 and sec["staff"]["mfa_enabled"] == 2
        assert {s["email"] for s in sec["admin_sessions"]} >= {"admin@ornek.com"}
        assert sec["events"][0]["action"] == "auth.login_failed"
        assert (await an.get("/admin/v1/security")).status_code == 403
        settings = await a.get("/admin/v1/settings")
        assert settings.status_code == 200 and KEK not in settings.text
        assert base64.b64decode(KEK).hex() not in settings.text
        matrix = (await a.get("/admin/v1/roles/matrix")).json()
        assert len(matrix["roles"]) == 7 and any(
            p["code"] == "finance.refund" and p["sensitive"] for p in matrix["permissions"]
        )
    clock.advance(minutes=1)
    assert timedelta(minutes=1)
