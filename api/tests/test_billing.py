"""Faz 6: paket hakları, ödeme (simülatör / PayTR / iyzico), abonelik, iade, lisans.

Kabul kriterleri:
* Haklar backend'de uygulanır (FREE kilitli içerik görmez; kupon/Kelly paket ister; günlük sınır).
* Fiyat yoksa veya sağlayıcı bağlı değilse satış kapalıdır.
* Sahte (yanlış imzalı) bildirim hiçbir şeyi değiştirmez ama kaydedilir.
* Aynı bildirim ikinci kez işlenmez; tutar uyuşmazlığında abonelik verilmez (inceleme).
* Ödeme → abonelik; ikinci dönem eskisinin bitişinden başlar. İade aboneliği sonlandırır.
* Lisans: düz metin bir kez, özet saklanır; kullanım sınırı, iptal, başarısız deneme denetimi.
* Gelir özeti yalnızca gerçek (test olmayan) kayıtlardan; kayıt yoksa ``None``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx
import psycopg
import pytest

from conftest import (
    Clock,
    grant_plan,
    make_settings,
    make_staff,
    member,
    new_client,
    signup_and_login,
    use,
)
from mi_api.billing.providers import (
    Buyer,
    CheckoutRequest,
    InvalidSignature,
    IyzicoProvider,
    PaytrProvider,
    ProviderError,
)
from mi_api.billing.service import normalize_key, simulator_secret

PEPPER = base64.b64encode(b"p" * 32).decode()
BUYER = {
    "full_name": "Ayşe Yılmaz",
    "phone": "5320000000",
    "address": "Adres 1",
    "city": "İstanbul",
}
PAYTR = {
    "merchant_id": "123456",
    "merchant_key": "paytr-key-abcdefgh",
    "merchant_salt": "salt-1234",
}
IYZICO = {"api_key": "sandbox-api-key-1", "secret_key": "sandbox-secret-key-1"}


def checkout(plan: str = "PRO", period: str = "monthly") -> dict[str, Any]:
    return {
        "plan": plan,
        "period": period,
        "buyer": BUYER,
        "accept_terms": True,
        "accept_distance_sales": True,
    }


def one(sql: psycopg.Connection[Any], query: str, params: tuple[Any, ...] = ()) -> Any:
    row = sql.execute(query, params).fetchone()
    return None if row is None else row[0]


def set_price(sql: psycopg.Connection[Any], plan: str, period: str, minor: int) -> None:
    sql.execute(
        "INSERT INTO plan_prices (plan_code, period, amount_minor, currency, active, created_at)"
        " VALUES (%s, %s, %s, 'TRY', true, now())",
        (plan, period, minor),
    )


def verify(sql: psycopg.Connection[Any], email: str) -> None:
    sql.execute("UPDATE users SET email_verified_at = now() WHERE email = %s", (email,))


async def buyer(app: Any, sql: psycopg.Connection[Any], email: str) -> httpx.AsyncClient:
    client = new_client(app)
    await signup_and_login(client, email)
    verify(sql, email)
    return client


async def sim_order(
    c: httpx.AsyncClient, plan: str = "PRO", period: str = "monthly"
) -> tuple[str, str]:
    r = await c.post("/v1/billing/checkout", json=checkout(plan, period))
    assert r.status_code == 201, r.text
    url = r.json()["redirect_url"]
    assert "/odeme/test?oturum=" in url
    return r.json()["order"]["id"], parse_qs(url.split("?", 1)[1])["oturum"][0]


def sim_app(app_factory: Any, **extra: Any) -> Any:
    return app_factory(payment_provider="simulator", license_pepper=PEPPER, **extra)


def signed(app: Any, payload: dict[str, Any]) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    secret = simulator_secret(app.state.services.settings)
    return body, hmac.new(secret, body, hashlib.sha256).hexdigest()


# --- Paket hakları -------------------------------------------------------------------------------


async def test_free_plan_is_enforced_in_backend(
    app: Any, sql: psycopg.Connection[Any], seeded: dict[str, Any]
) -> None:
    fixture = seeded["fixtures"][0]
    async with new_client(app) as anon:
        body = (await anon.get(f"/v1/predictions/fixtures/{fixture}")).json()
        probs = body["probabilities"]
        assert set(probs) == {"1x2"}  # FREE: yalnızca maç sonucu
        assert body["access"]["plan"] == "FREE"
        locked = {x["key"] for x in body["access"]["locked"]}
        assert "predictions.markets" in locked and body["uncertainty"] == {}
    async with new_client(app) as c:
        await signup_and_login(c, "free@ornek.com")
        r = await c.post("/v1/coupons/generate", json={"date": "2026-11-20", "size": 2})
        assert r.status_code == 403 and r.json()["code"] == "plan_required"
        await c.post("/v1/virtual/account", json={"accept": True})
        r = await c.put("/v1/virtual/settings", json={"method": "kelly", "kelly_fraction": 0.25})
        assert r.status_code == 403 and r.json()["code"] == "plan_required"
        me = (await c.get("/v1/billing/me")).json()
        assert me["plan"] == "FREE" and me["current"] is None
    async with new_client(app) as pro:
        await member(pro, sql, "pro@ornek.com", plan="PRO")
        body = (await pro.get(f"/v1/predictions/fixtures/{fixture}")).json()
        probs = body["probabilities"]
        assert "1x2" in probs and len(probs) > 1 and "score_matrix" not in probs
        assert body["model"]["components"] == {}  # bileşenler ELITE
        r = await pro.post("/v1/coupons/generate", json={"date": "2026-11-20", "size": 7})
        assert r.status_code == 403 and r.json()["code"] == "plan_limit"


async def test_daily_limit_and_admin_entitlements(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, Any]
) -> None:
    admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    async with use(support.client) as s:
        r = await s.put(
            "/admin/v1/billing/plans/PRO/entitlements",
            json={"values": {"coupons.daily_generate": 1}},
        )
        assert r.status_code == 403
    async with use(admin.client) as a:
        for bad in ({"bilinmeyen.hak": True}, {"coupons.max_legs": 99}, {"coupons.enabled": 1}):
            r = await a.put("/admin/v1/billing/plans/PRO/entitlements", json={"values": bad})
            assert r.status_code == 422, bad
        r = await a.put(
            "/admin/v1/billing/plans/PRO/entitlements",
            json={"values": {"coupons.daily_generate": 1}},
        )
        assert r.status_code == 200, r.text
    assert (
        one(sql, "SELECT count(*) FROM audit_log WHERE action='billing.entitlements_changed'") == 1
    )
    async with new_client(app) as c:
        await member(c, sql, "pro@ornek.com", plan="PRO")
        body = {"date": "2026-11-20", "profile": "low", "size": 2}
        assert (await c.post("/v1/coupons/generate", json=body)).status_code == 200
        r = await c.post("/v1/coupons/generate", json=body)
        assert r.status_code == 429 and r.json()["code"] == "daily_limit"
        assert (await c.get("/v1/billing/me")).json()["usage_today"] == {"coupons.generate": 1}


# --- Satış ve simülatör --------------------------------------------------------------------------


async def test_sales_closed_without_provider_or_price(
    app_factory: Any, sql: psycopg.Connection[Any]
) -> None:
    closed = app_factory()
    async with use(await buyer(closed, sql, "a@ornek.com")) as c:
        plans = (await c.get("/v1/billing/plans")).json()
        assert plans["sales"]["open"] is False
        assert all(p["prices"] == {} for p in plans["plans"])  # uydurma fiyat yok
        r = await c.post("/v1/billing/checkout", json=checkout())
        assert (
            r.status_code == 409 and r.json()["code"] == "price_not_set"
        ) or r.status_code == 503
    app = sim_app(app_factory)
    async with use(await buyer(app, sql, "b@ornek.com")) as c:
        r = await c.post("/v1/billing/checkout", json=checkout())
        assert r.status_code == 409 and r.json()["code"] == "price_not_set"
        set_price(sql, "PRO", "monthly", 19900)
        bad = {**checkout(), "accept_distance_sales": False}
        assert (await c.post("/v1/billing/checkout", json=bad)).status_code == 422
    async with new_client(app) as c:
        await signup_and_login(c, "dogrulanmamis@ornek.com")
        r = await c.post("/v1/billing/checkout", json=checkout())
        assert r.status_code == 403 and r.json()["code"] == "email_unverified"


async def test_simulator_payment_grants_and_extends_subscription(
    app_factory: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    app = sim_app(app_factory)
    set_price(sql, "PRO", "monthly", 19900)
    async with use(await buyer(app, sql, "musteri@ornek.com")) as c:
        order_id, token = await sim_order(c)
        assert one(sql, "SELECT status FROM orders WHERE public_id=%s", (order_id,)) == "pending"
        session = (await c.get("/v1/billing/simulator/session", params={"token": token})).json()
        assert session["order"]["amount_minor"] == 19900 and session["test_mode"] is True
        async with use(await buyer(app, sql, "baska@ornek.com")) as other:
            r = await other.post(
                "/v1/billing/simulator/complete", json={"token": token, "outcome": "success"}
            )
            assert r.status_code == 404  # başkasının siparişi
        forged = token.split(".")[0] + ".00000000000000000000000000000000"
        r = await c.post(
            "/v1/billing/simulator/complete", json={"token": forged, "outcome": "success"}
        )
        assert r.status_code == 400

        r = await c.post(
            "/v1/billing/simulator/complete", json={"token": token, "outcome": "success"}
        )
        assert r.status_code == 200 and r.json()["result"] == "paid"
        assert r.json()["order"]["status"] == "paid"
        me = (await c.get("/v1/billing/me")).json()
        assert me["plan"] == "PRO" and me["current"]["source"] == "payment"
        first_end = me["current"]["current_period_end"]
        assert (await c.get(f"/v1/billing/orders/{order_id}")).json()["status"] == "paid"
        r = await c.post(
            "/v1/billing/simulator/complete", json={"token": token, "outcome": "success"}
        )
        assert r.status_code == 409  # sonuçlanmış sipariş

        _, token2 = await sim_order(c)
        r = await c.post(
            "/v1/billing/simulator/complete", json={"token": token2, "outcome": "success"}
        )
        assert r.json()["result"] == "paid"
        subs = sql.execute(
            "SELECT started_at, current_period_end FROM subscriptions ORDER BY id"
        ).fetchall()
        assert len(subs) == 2 and subs[1][0] == subs[0][1]  # yeni dönem eskinin bitişinden
        assert subs[1][1] - subs[0][1] == timedelta(days=30)
        assert first_end == subs[0][1].isoformat()

        _, token3 = await sim_order(c)
        r = await c.post(
            "/v1/billing/simulator/complete", json={"token": token3, "outcome": "fail"}
        )
        assert r.json()["result"] == "failed" and r.json()["order"]["status"] == "failed"
    assert one(sql, "SELECT count(*) FROM subscriptions") == 2
    # Satın alma akışı denetim kaydında.
    actions = [r[0] for r in sql.execute("SELECT action FROM audit_log").fetchall()]
    assert actions.count("billing.webhook_paid") == 2 and "billing.checkout_started" in actions


async def test_forged_replayed_and_mismatched_webhooks(
    app_factory: Any, sql: psycopg.Connection[Any]
) -> None:
    app = sim_app(app_factory)
    set_price(sql, "ELITE", "yearly", 199900)
    async with use(await buyer(app, sql, "musteri@ornek.com")) as c:
        order_id, _ = await sim_order(c, "ELITE", "yearly")
    machine = new_client(app, origin="https://sim.example")  # bildirimde köken denetimi yok
    payload = {
        "id": "sim_evt_1", "type": "payment_succeeded", "order_id": order_id,
        "payment_id": "sim_pay_1", "amount_minor": 199900, "currency": "TRY",
    }  # fmt: skip
    body, sig = signed(app, payload)
    async with use(machine) as m:
        r = await m.post(
            "/v1/billing/webhooks/simulator",
            content=body,
            headers={"x-simulator-signature": "0" * 64},
        )
        assert r.status_code == 400 and r.json()["code"] == "invalid_signature"
        assert one(sql, "SELECT status FROM orders") == "pending"
        assert one(sql, "SELECT count(*) FROM payment_events WHERE NOT signature_valid") == 1
        for _ in range(2):  # sağlayıcı yeniden gönderir
            r = await m.post(
                "/v1/billing/webhooks/simulator",
                content=body,
                headers={"x-simulator-signature": sig},
            )
            assert r.status_code == 200
        assert [json.loads(r.content)["result"]] == ["duplicate"]
        assert one(sql, "SELECT count(*) FROM subscriptions") == 1
        assert one(sql, "SELECT plan_code FROM subscriptions") == "ELITE"
        end = one(sql, "SELECT current_period_end - started_at FROM subscriptions")
        assert end == timedelta(days=365)
        # Aynı siparişe farklı kimlikli ikinci başarılı ödeme: abonelik verilmez, not düşülür.
        body2, sig2 = signed(app, {**payload, "id": "sim_evt_2", "payment_id": "sim_pay_2"})
        r = await m.post(
            "/v1/billing/webhooks/simulator", content=body2, headers={"x-simulator-signature": sig2}
        )
        assert json.loads(r.content)["result"] == "second_payment"
        assert one(sql, "SELECT count(*) FROM subscriptions") == 1
        with pytest.raises(psycopg.Error):
            sql.execute("UPDATE payment_events SET result = 'paid'")

    async with use(await buyer(app, sql, "ikinci@ornek.com")) as c:
        order2, _ = await sim_order(c, "ELITE", "yearly")
    body3, sig3 = signed(
        app, {**payload, "id": "sim_evt_3", "order_id": order2, "amount_minor": 100}
    )
    async with new_client(app, origin="https://sim.example") as m:
        r = await m.post(
            "/v1/billing/webhooks/simulator", content=body3, headers={"x-simulator-signature": sig3}
        )
        assert json.loads(r.content)["result"] == "mismatch"
        unknown, sig4 = signed(app, {**payload, "id": "sim_evt_4", "order_id": str(uuid.uuid4())})
        r = await m.post(
            "/v1/billing/webhooks/simulator",
            content=unknown,
            headers={"x-simulator-signature": sig4},
        )
        assert json.loads(r.content)["result"] == "unknown_order"
        assert (await m.post("/v1/billing/webhooks/paytr", content=b"x")).status_code == 404
    assert one(sql, "SELECT status FROM orders WHERE public_id=%s", (order2,)) == "review"
    assert one(sql, "SELECT count(*) FROM subscriptions") == 1


async def test_refund_ends_subscription(
    app_factory: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    app = sim_app(app_factory)
    set_price(sql, "PRO", "monthly", 19900)
    async with use(await buyer(app, sql, "musteri@ornek.com")) as c:
        _, token = await sim_order(c)
        await c.post("/v1/billing/simulator/complete", json={"token": token, "outcome": "success"})
        assert (await c.get("/v1/billing/me")).json()["plan"] == "PRO"
        number = one(sql, "SELECT id FROM orders")
        admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
        async with use(admin.client) as a:
            assert (await a.get("/admin/v1/billing/orders")).status_code == 200
            assert (await a.post(f"/admin/v1/billing/orders/{number}/refund")).status_code == 403
        finance = await make_staff(app, sql, clock, "finans@ornek.com", "FINANCE_MANAGER")
        async with use(finance.client) as f:
            r = await f.post(f"/admin/v1/billing/orders/{number}/refund")
            assert r.status_code == 200 and r.json()["status"] == "refunded"
            assert (await f.post(f"/admin/v1/billing/orders/{number}/refund")).status_code == 409
            summary = (await f.get("/admin/v1/billing/summary")).json()
            # Simülatör test modudur: gelir metriklerine girmez, uydurma değer yok.
            assert summary["revenue"] is None and summary["mrr_minor"] is None
            assert summary["arpu_30d_minor"] is None and summary["churn_30d"] is None
        me = (await c.get("/v1/billing/me")).json()
        assert me["plan"] == "FREE" and me["subscriptions"][0]["status"] == "refunded"
    assert one(sql, "SELECT count(*) FROM audit_log WHERE action='billing.refunded'") == 1


async def test_admin_grant_revoke_and_prices(
    app: Any, sql: psycopg.Connection[Any], clock: Clock
) -> None:
    async with new_client(app) as u:
        await signup_and_login(u, "uye@ornek.com")
        admin = await make_staff(app, sql, clock, "admin@ornek.com", "ADMIN")
        async with use(admin.client) as a:
            r = await a.put(
                "/admin/v1/billing/plans/FREE/prices",
                json={"period": "monthly", "amount_minor": 1000},
            )
            assert r.status_code == 422
            for amount in (19900, 24900):
                r = await a.put(
                    "/admin/v1/billing/plans/PRO/prices",
                    json={"period": "monthly", "amount_minor": amount},
                )
                assert r.status_code == 200
            pro = next(p for p in r.json()["plans"] if p["code"] == "PRO")
            assert pro["prices"]["monthly"]["amount_minor"] == 24900
            assert one(sql, "SELECT count(*) FROM plan_prices WHERE active") == 1
            r = await a.post(
                "/admin/v1/billing/subscriptions/grant",
                json={"email": "UYE@ornek.com", "plan": "ELITE", "days": 14, "note": "destek"},
            )
            assert r.status_code == 201, r.text
            sub_id = r.json()["id"]
            assert (await u.get("/v1/billing/me")).json()["plan"] == "ELITE"
            assert (
                await a.post(f"/admin/v1/billing/subscriptions/{sub_id}/revoke")
            ).status_code == 200
            assert (
                await a.post(f"/admin/v1/billing/subscriptions/{sub_id}/revoke")
            ).status_code == 409
            assert (await u.get("/v1/billing/me")).json()["plan"] == "FREE"
            listed = (await a.get("/admin/v1/billing/subscriptions")).json()["items"]
            assert listed[0]["email"] == "uye@ornek.com" and listed[0]["status"] == "revoked"
            r = await a.delete("/admin/v1/billing/plans/PRO/prices/monthly")
            assert r.status_code == 200
            assert one(sql, "SELECT count(*) FROM plan_prices WHERE active") == 0
    # Süre bitince FREE'ye düşer.
    grant_plan(sql, "uye@ornek.com", "PRO", clock(), days=1)
    async with new_client(app) as u:
        await u.post(
            "/v1/auth/login", json={"email": "uye@ornek.com", "password": "Gizli-Parola-2026!"}
        )
        assert (await u.get("/v1/billing/me")).json()["plan"] == "PRO"
        clock.advance(days=2)
        assert (await u.get("/v1/billing/me")).json()["plan"] == "FREE"


# --- Lisans anahtarları --------------------------------------------------------------------------


async def test_license_keys(app_factory: Any, sql: psycopg.Connection[Any], clock: Clock) -> None:
    no_pepper = app_factory()
    staff = await make_staff(no_pepper, sql, clock, "fin0@ornek.com", "FINANCE_MANAGER")
    async with use(staff.client) as f:
        r = await f.post("/admin/v1/billing/licenses", json={"plan": "PRO", "duration_days": 30})
        assert r.status_code == 503

    app = app_factory(license_pepper=PEPPER)
    finance = await make_staff(app, sql, clock, "finans@ornek.com", "FINANCE_MANAGER")
    async with use(finance.client) as f:
        r = await f.post(
            "/admin/v1/billing/licenses",
            json={"plan": "ELITE", "duration_days": 30, "count": 2, "max_activations": 1},
        )
        assert r.status_code == 201, r.text
        keys = [x["key"] for x in r.json()["items"]]
        ids = [x["id"] for x in r.json()["items"]]
        assert all(k.startswith("MI-") and len(k) == 22 for k in keys)
        listed = (await f.get("/admin/v1/billing/licenses")).json()["items"]
        assert all("key" not in x for x in listed)  # düz metin bir daha gösterilmez
        stored = sql.execute("SELECT key_digest, key_hint FROM licenses").fetchall()
        assert all(len(d) == 32 and keys[0].encode() not in bytes(d) for d, _ in stored)
        assert (await f.post(f"/admin/v1/billing/licenses/{ids[1]}/revoke")).status_code == 200

    async with new_client(app) as a, new_client(app) as b:
        await signup_and_login(a, "a@ornek.com")
        await signup_and_login(b, "b@ornek.com")
        sloppy = keys[0].lower().replace("-", " ")  # boşluk/küçük harf toleransı
        assert normalize_key(sloppy) == normalize_key(keys[0])
        r = await a.post("/v1/billing/licenses/redeem", json={"key": sloppy})
        assert r.status_code == 200, r.text
        assert r.json()["subscription"]["plan"] == "ELITE"
        assert (await a.get("/v1/billing/me")).json()["plan"] == "ELITE"
        r = await a.post("/v1/billing/licenses/redeem", json={"key": keys[0]})
        assert r.status_code == 409 and r.json()["code"] == "already_redeemed"
        for key in (keys[0], keys[1], "MI-AAAA-BBBB-CCCC-DDDD"):  # dolu, iptal, uydurma
            r = await b.post("/v1/billing/licenses/redeem", json={"key": key})
            assert r.status_code == 400 and r.json()["code"] == "invalid_license"
        statuses = [
            (
                await b.post("/v1/billing/licenses/redeem", json={"key": "MI-AAAA-BBBB-CCCC-EEEE"})
            ).status_code
            for _ in range(3)
        ]
        assert statuses == [400, 400, 429]  # 15 dakikada 5 deneme
    assert (
        one(sql, "SELECT count(*) FROM audit_log WHERE action='billing.license_redeem_failed'") == 5
    )
    assert one(sql, "SELECT activations_count FROM licenses WHERE id=%s", (ids[0],)) == 1


# --- PayTR ve iyzico -----------------------------------------------------------------------------


def paytr_hash(text: str) -> str:
    digest = hmac.new(PAYTR["merchant_key"].encode(), text.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_paytr_token_and_callback_signature() -> None:
    provider = PaytrProvider(**PAYTR, test_mode=True)
    request = CheckoutRequest(
        order_id=str(uuid.uuid4()), order_no=100042, amount_minor=19990, currency="TRY",
        item_name="Match Intelligence PRO (aylık)", plan_code="PRO",
        buyer=Buyer(customer_id="c", email="a@example.com", full_name="Ayşe Yılmaz",
                    phone="5320000000", address="Adres 1", city="İstanbul", country="Türkiye",
                    ip="203.0.113.5"),
        success_url="https://ornek.com/odeme/sonuc", fail_url="https://ornek.com/odeme/sonuc",
        callback_url="https://api.ornek.com/v1/billing/webhooks/paytr",
    )  # fmt: skip
    fields = provider.token_fields(request)
    assert fields["merchant_oid"] == "MI100042" and fields["payment_amount"] == "19990"
    assert fields["currency"] == "TL" and fields["test_mode"] == "1"
    assert json.loads(base64.b64decode(fields["user_basket"])) == [
        ["Match Intelligence PRO (aylık)", "199.90", 1]
    ]
    expected = paytr_hash(
        "123456" + "203.0.113.5" + "MI100042" + "a@example.com" + "19990"
        + fields["user_basket"] + "1" + "0" + "TL" + "1" + PAYTR["merchant_salt"]
    )  # fmt: skip
    assert fields["paytr_token"] == expected
    form = {"merchant_oid": "MI100042", "status": "success", "total_amount": "19990",
            "payment_amount": "19990", "currency": "TL"}  # fmt: skip
    form["hash"] = paytr_hash("MI100042" + PAYTR["merchant_salt"] + "success" + "19990")
    event = provider.parse_webhook({}, urlencode(form).encode())
    assert event.event_type == "payment_succeeded" and event.order_ref == "MI100042"
    assert event.amount_minor == 19990 and event.currency == "TRY"
    for key, value in (("status", "failed"), ("total_amount", "1"), ("hash", "AAAA")):
        with pytest.raises(InvalidSignature):
            provider.parse_webhook({}, urlencode({**form, key: value}).encode())


async def test_paytr_checkout_and_callback_through_api(
    app_factory: Any, sql: psycopg.Connection[Any]
) -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/odeme/api/get-token"
        seen.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"status": "success", "token": "ifr-token-1"})

    app = app_factory(
        payment_provider="paytr", paytr_merchant_id=PAYTR["merchant_id"],
        paytr_merchant_key=PAYTR["merchant_key"], paytr_merchant_salt=PAYTR["merchant_salt"],
        payment_transport=httpx.MockTransport(handler),
    )  # fmt: skip
    set_price(sql, "PRO", "monthly", 19990)
    async with use(await buyer(app, sql, "musteri@ornek.com")) as c:
        r = await c.post("/v1/billing/checkout", json=checkout())
        assert r.status_code == 201, r.text
        assert r.json()["redirect_url"] == "https://www.paytr.com/odeme/guvenli/ifr-token-1"
        number = r.json()["order"]["number"]
        assert seen[0]["merchant_oid"] == f"MI{number}" and seen[0]["test_mode"] == "1"
        assert seen[0]["email"] == "musteri@ornek.com"
    oid = f"MI{number}"
    form = {"merchant_oid": oid, "status": "success", "total_amount": "19990",
            "payment_amount": "19990", "currency": "TL", "test_mode": "1"}  # fmt: skip
    headers = {"content-type": "application/x-www-form-urlencoded"}
    async with new_client(app, origin="https://www.paytr.com") as m:
        bad = await m.post(
            "/v1/billing/webhooks/paytr",
            content=urlencode({**form, "hash": "AAAA"}),
            headers=headers,
        )
        assert bad.status_code == 400
        form["hash"] = paytr_hash(oid + PAYTR["merchant_salt"] + "success" + "19990")
        for _ in range(2):  # PayTR "OK" alana kadar yeniden dener
            ok = await m.post(
                "/v1/billing/webhooks/paytr", content=urlencode(form), headers=headers
            )
            assert ok.status_code == 200 and ok.text == "OK"
    assert one(sql, "SELECT status FROM orders") == "paid"
    assert one(sql, "SELECT count(*) FROM subscriptions") == 1


def iyzico_signature_ok(request: httpx.Request) -> bool:
    auth = request.headers["authorization"]
    decoded = base64.b64decode(auth.removeprefix("IYZWSv2 ")).decode()
    parts = dict(p.split(":", 1) for p in decoded.split("&"))
    expected = hmac.new(
        IYZICO["secret_key"].encode(),
        (parts["randomKey"] + request.url.path + request.content.decode()).encode(),
        hashlib.sha256,
    ).hexdigest()
    return parts["apiKey"] == IYZICO["api_key"] and hmac.compare_digest(
        parts["signature"], expected
    )


async def test_iyzico_checkout_and_return(app_factory: Any, sql: psycopg.Connection[Any]) -> None:
    state: dict[str, Any] = {"basket": None, "status": "SUCCESS", "price": "199.90"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "sandbox-api.iyzipay.com" and iyzico_signature_ok(request)
        body = json.loads(request.content)
        if request.url.path == IyzicoProvider.INIT:
            state["basket"] = body["basketId"]
            assert body["price"] == "199.90" and body["callbackUrl"].endswith(
                "/v1/billing/webhooks/iyzico"
            )
            return httpx.Response(200, json={"status": "success", "token": "tok-1",
                                             "paymentPageUrl": "https://sandbox-cpp.iyzipay.com/?token=x"})  # fmt: skip
        if body["token"] == "bozuk":
            return httpx.Response(200, json={"status": "failure", "errorMessage": "x"})
        return httpx.Response(200, json={
            "status": "success", "paymentStatus": state["status"], "paidPrice": state["price"],
            "currency": "TRY", "basketId": state["basket"], "paymentId": "pay-1",
        })  # fmt: skip

    app = app_factory(
        payment_provider="iyzico", iyzico_api_key=IYZICO["api_key"],
        iyzico_secret_key=IYZICO["secret_key"], payment_transport=httpx.MockTransport(handler),
    )  # fmt: skip
    set_price(sql, "PRO", "monthly", 19990)
    async with use(await buyer(app, sql, "musteri@ornek.com")) as c:
        r = await c.post("/v1/billing/checkout", json=checkout())
        assert r.status_code == 201, r.text
        assert r.json()["redirect_url"] == "https://sandbox-cpp.iyzipay.com/?token=x"
        order_id = r.json()["order"]["id"]
    form = {"content-type": "application/x-www-form-urlencoded"}
    async with new_client(app, origin="null") as browser:
        back = await browser.post(
            "/v1/billing/webhooks/iyzico", content="token=bozuk", headers=form
        )
        assert back.status_code == 303 and back.headers["location"].endswith("hata=dogrulanamadi")
        for _ in range(2):
            back = await browser.post(
                "/v1/billing/webhooks/iyzico", content="token=tok-1", headers=form
            )
            assert back.status_code == 303
            assert back.headers["location"].endswith(f"/odeme/sonuc?siparis={order_id}")
    assert one(sql, "SELECT status FROM orders") == "paid"
    assert one(sql, "SELECT count(*) FROM subscriptions") == 1


async def test_iyzico_provider_errors_are_reported() -> None:
    provider = IyzicoProvider(
        api_key="k", secret_key="s", test_mode=False,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "failure", "errorMessage": "x"})
        ),
    )  # fmt: skip
    assert provider.base_url == IyzicoProvider.LIVE
    with pytest.raises(ProviderError):
        await provider.refund(
            provider_payment_id="1", amount_minor=100, currency="TRY", order_ref="o"
        )


def test_payment_config_guards(dsn: str) -> None:
    with pytest.raises(ValueError, match="M-G5"):
        make_settings(dsn, payment_provider="paytr", payments_test_mode=False)  # M-G5 onayı yok
    with pytest.raises(ValueError, match="simülatörü"):
        make_settings(dsn, environment="production", payment_provider="simulator")
    ok = make_settings(
        dsn, payment_provider="paytr", payments_test_mode=False, payments_live_allowed=True
    )
    assert ok.payments_test_mode is False
