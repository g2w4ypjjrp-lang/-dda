"""Sanal portföy: tutar hesapları, değiştirilemez defter, risk sınırları, sonuçlandırma, rapor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from conftest import Clock, make_staff, new_client, signup_and_login, use
from coupon_support import NOW
from mi_api.errors import ApiError
from mi_api.virtual import service
from mi_api.virtual.service import (
    Settings,
    compute_stake,
    fair_odds,
    increases_risk,
    kelly_fraction,
    max_drawdown,
)

SB = service.UNIT


# --- Saf hesaplar ---------------------------------------------------------------------------------


def test_stake_methods_and_caps() -> None:
    bal = 10_000 * SB
    assert compute_stake(Settings(method="percent", percent=1.0), bal, 0.5, 2.0)[0] == 100 * SB
    assert (
        compute_stake(Settings(method="fixed", fixed_minor=300 * SB), bal, 0.5, 2.0)[0] == 300 * SB
    )
    capped, detail = compute_stake(
        Settings(method="fixed", fixed_minor=900 * SB, max_stake_pct=5), bal, 0.5, 2.0
    )
    assert capped == 500 * SB and detail["capped"] is True
    # Kelly: p=0.6, o=2.0 → f*=0.2; çeyrek Kelly → %5 → sınır %5.
    stake, detail = compute_stake(Settings(method="kelly", kelly_fraction=0.25), bal, 0.6, 2.0)
    assert detail["kelly_full"] == pytest.approx(0.2) and stake == 500 * SB
    with pytest.raises(ApiError) as err:
        compute_stake(Settings(method="kelly"), bal, 0.5, float(fair_odds(0.5)))
    assert err.value.code == "no_edge"  # adil oranda avantaj yok
    with pytest.raises(ApiError):
        compute_stake(Settings(method="percent", percent=0.1), 50 * SB, 0.5, 2.0)  # 0.05 SB < 1 SB


def test_kelly_and_fair_odds() -> None:
    assert kelly_fraction(0.5, 2.0) == 0.0
    assert kelly_fraction(0.4, 2.0) == 0.0
    assert fair_odds(0.25) == Decimal("4.000")
    assert fair_odds(0.999) == Decimal("1.001")


def test_risk_increase_detection() -> None:
    base = Settings()
    assert not increases_risk(base, Settings(percent=0.5, max_daily_tickets=3))
    assert increases_risk(base, Settings(percent=2.0))
    assert increases_risk(base, Settings(method="fixed"))
    assert increases_risk(base, Settings(daily_risk_pct=20))


def test_max_drawdown() -> None:
    assert max_drawdown([100, 120, 90, 130, 65]) == pytest.approx(0.5)
    assert max_drawdown([100, 110, 120]) == 0.0


# --- API + veritabanı ----------------------------------------------------------------------------


async def _coupon(c: Any, pred: int, market: str = "1x2", pick: str = "home") -> dict[str, Any]:
    r = await c.post(
        "/v1/coupons", json={"legs": [{"prediction_id": pred, "market": market, "pick": pick}]}
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_account_ledger_and_tickets(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, Any]
) -> None:
    p = seeded["preds"]
    async with new_client(app) as c:
        await signup_and_login(c, "sanal@ornek.com")
        assert (await c.get("/v1/virtual/account")).json()["code"] == "no_account"
        assert (await c.post("/v1/virtual/account", json={"accept": False})).status_code == 422
        acc = (await c.post("/v1/virtual/account", json={"accept": True})).json()
        assert acc["balance_minor"] == 10_000 * SB and "gerçek para değildir" in acc["disclaimer"]
        assert (await c.post("/v1/virtual/account", json={"accept": True})).json()[
            "code"
        ] == "account_exists"

        coupon = await _coupon(c, p[0])
        r = await c.post("/v1/virtual/tickets", json={"coupon_id": coupon["id"]})
        assert r.status_code == 201, r.text
        t = r.json()["ticket"]
        assert (
            t["stake_minor"] == 100 * SB
            and t["odds_source"] == "model_fair"
            and t["model_ev"] is None
        )
        assert t["odds"] == pytest.approx(float(fair_odds(coupon["joint_probability"])))
        assert r.json()["account"]["balance_minor"] == 9_900 * SB
        assert (await c.post("/v1/virtual/tickets", json={"coupon_id": coupon["id"]})).json()[
            "code"
        ] == "ticket_exists"

        # Kullanıcı oranı: EV gösterilir ama "doğrulanmamış" etiketiyle.
        c2 = await _coupon(c, p[1], "double_chance", "1X")
        t2 = (
            await c.post(
                "/v1/virtual/tickets",
                json={"coupon_id": c2["id"], "odds_source": "user_entered", "odds": "1.40"},
            )
        ).json()["ticket"]
        assert t2["model_ev"] == pytest.approx(t2["model_probability"] * 1.40 - 1)
        assert "doğrulanmamış" in t2["odds_note"]
        assert (
            await c.post(
                "/v1/virtual/tickets",
                json={"coupon_id": (await _coupon(c, p[2]))["id"], "odds_source": "user_entered"},
            )
        ).json()["code"] == "odds_required"

    # Defter ve bakiye değiştirilemez.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("UPDATE virtual_ledger SET amount_minor = 999999999")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("UPDATE virtual_accounts SET balance_minor = 999999999")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("DELETE FROM virtual_tickets")
    acc_id = sql.execute("SELECT id FROM virtual_accounts").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):  # bakiye eksiye düşemez
        sql.execute(
            "INSERT INTO virtual_ledger (account_id, created_at, kind, amount_minor, balance_minor, note) VALUES (%s, now(), 'reset', -999999999, 0, 'x')",
            (acc_id,),
        )
    rows = sql.execute(
        "SELECT kind, amount_minor, balance_minor FROM virtual_ledger ORDER BY id"
    ).fetchall()
    assert rows[0] == ("opening", 10_000 * SB, 10_000 * SB)
    assert all(rows[i][2] == rows[i - 1][2] + rows[i][1] for i in range(1, len(rows)))


async def test_limits_and_deferred_risk(app: Any, clock: Clock, seeded: dict[str, Any]) -> None:
    p = seeded["preds"]
    async with new_client(app) as c:
        await signup_and_login(c, "limit@ornek.com")
        await c.post("/v1/virtual/account", json={"accept": True})
        # Riski azaltan değişiklik hemen.
        r = (
            await c.put(
                "/v1/virtual/settings", json={**Settings().model_dump(), "max_daily_tickets": 1}
            )
        ).json()
        assert r["applied"] is True and r["account"]["settings"]["max_daily_tickets"] == 1
        # Riski artıran değişiklik ertesi gün.
        r = (
            await c.put(
                "/v1/virtual/settings",
                json={**Settings().model_dump(), "max_daily_tickets": 1, "percent": 4.0},
            )
        ).json()
        assert r["applied"] is False and r["effective_at"] == "2026-11-20T21:00:00+00:00"
        assert r["account"]["settings"]["percent"] == 1.0
        assert (
            await c.post("/v1/virtual/tickets", json={"coupon_id": (await _coupon(c, p[0]))["id"]})
        ).status_code == 201
        r = await c.post("/v1/virtual/tickets", json={"coupon_id": (await _coupon(c, p[1]))["id"]})
        assert r.json()["code"] == "daily_ticket_limit"
        # Kelly + adil oran: işlem önermez.
        await c.put(
            "/v1/virtual/settings",
            json={**Settings().model_dump(), "method": "kelly", "max_daily_tickets": 1},
        )
        clock.advance(hours=13)  # TR gece yarısını geçti: bekleyen ayarlar uygulanır
        acc = (await c.get("/v1/virtual/account")).json()
        assert acc["settings"]["method"] == "kelly" and acc["pending_settings"] is None
        clock.now = NOW  # maçlar başlamadan geri dön (yalnızca test saatini)


async def test_daily_risk_cap(app: Any, seeded: dict[str, Any]) -> None:
    p = seeded["preds"]
    async with new_client(app) as c:
        await signup_and_login(c, "risk@ornek.com")
        await c.post("/v1/virtual/account", json={"accept": True})
        # Yalnızca riski azaltan değişiklik (hemen uygulanır): günlük risk %1 = 100 SB.
        r = (
            await c.put(
                "/v1/virtual/settings", json={**Settings().model_dump(), "daily_risk_pct": 1.0}
            )
        ).json()
        assert r["applied"] is True
        assert (
            await c.post("/v1/virtual/tickets", json={"coupon_id": (await _coupon(c, p[0]))["id"]})
        ).status_code == 201
        r = await c.post("/v1/virtual/tickets", json={"coupon_id": (await _coupon(c, p[1]))["id"]})
        assert r.json()["code"] == "daily_risk_limit"


async def test_settlement_report_reset(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, Any]
) -> None:
    p, fx = seeded["preds"], seeded["fixtures"]
    async with new_client(app) as c:
        await signup_and_login(c, "rapor@ornek.com")
        await c.post("/v1/virtual/account", json={"accept": True})
        win = await _coupon(c, p[0])  # ev sahibi kazanır
        lose = await _coupon(c, p[1], "1x2", "away")
        void = await _coupon(c, p[2])
        tw = (await c.post("/v1/virtual/tickets", json={"coupon_id": win["id"]})).json()["ticket"]
        await c.post("/v1/virtual/tickets", json={"coupon_id": lose["id"]})
        await c.post("/v1/virtual/tickets", json={"coupon_id": void["id"]})
        assert (await c.post("/v1/virtual/reset")).json()["code"] == "pending_tickets"

        sql.execute(
            "UPDATE football_fixtures SET status='finished', status_detail='FT', home_goals=2, away_goals=0, ft_home=2, ft_away=0 WHERE id = ANY(%s)",
            ([fx[0], fx[1]],),
        )
        sql.execute("UPDATE football_fixtures SET status='cancelled' WHERE id=%s", (fx[2],))
        analyst = await make_staff(app, sql, clock, "analist@ornek.com", "ANALYST")
        async with use(analyst.client) as a:
            await a.post("/admin/v1/coupons/settle")
            summary = (await a.get("/admin/v1/virtual")).json()
            assert (
                summary["tickets"] == {"won": 1, "lost": 1, "void": 1}
                and "gerçek para değildir" in summary["label"]
            )

        tickets = {t["coupon_id"]: t for t in (await c.get("/v1/virtual/tickets")).json()["items"]}
        payout = int(tw["stake_minor"] * tw["odds"])
        assert tickets[win["id"]]["status"] == "won" and tickets[win["id"]][
            "payout_minor"
        ] == pytest.approx(payout, abs=1)
        assert tickets[lose["id"]]["payout_minor"] == 0
        assert (
            tickets[void["id"]]["status"] == "void"
            and tickets[void["id"]]["payout_minor"] == tickets[void["id"]]["stake_minor"]
        )

        rep = (await c.get("/v1/virtual/report")).json()
        staked = tickets[win["id"]]["stake_minor"] + tickets[lose["id"]]["stake_minor"]
        assert rep["settled_staked_minor"] == staked
        assert rep["simulated_roi"] == pytest.approx(
            (tickets[win["id"]]["payout_minor"] - staked) / staked
        )
        assert rep["tickets"] == {"total": 3, "pending": 0, "won": 1, "lost": 1, "void": 1}
        assert rep["max_drawdown"] is not None and rep["balance_series"][0]["kind"] == "opening"
        assert "Simüle" in rep["label"]

        before = (await c.get("/v1/virtual/account")).json()
        r = (await c.post("/v1/virtual/reset")).json()
        assert (
            r["balance_minor"] == 10_000 * SB
            and r["reset_count"] == 1
            and before["balance_minor"] != r["balance_minor"]
        )
        assert (await c.post("/v1/virtual/reset")).json()["code"] == "reset_cooldown"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("UPDATE virtual_tickets SET payout_minor = 1 WHERE status = 'won'")


async def test_ticket_requires_own_open_coupon(
    app: Any, clock: Clock, seeded: dict[str, Any]
) -> None:
    p = seeded["preds"]
    async with new_client(app) as a, new_client(app) as b:
        await signup_and_login(a, "a@ornek.com")
        await signup_and_login(b, "b@ornek.com")
        await b.post("/v1/virtual/account", json={"accept": True})
        coupon = await _coupon(a, p[0])
        assert (
            await b.post("/v1/virtual/tickets", json={"coupon_id": coupon["id"]})
        ).status_code == 404
        await a.post("/v1/virtual/account", json={"accept": True})
        clock.advance(hours=3)  # maç başladı
        assert (await a.post("/v1/virtual/tickets", json={"coupon_id": coupon["id"]})).json()[
            "code"
        ] == "coupon_closed"


def test_no_payment_routes(app: Any) -> None:
    paths = set(app.openapi()["paths"])
    assert not any(
        k in p
        for p in paths
        if p.startswith("/v1/virtual")
        for k in ("withdraw", "transfer", "deposit", "cash")
    )
    assert datetime.now(UTC) > NOW - timedelta(days=3650)
