"""Kupon API'si: üretme, kaydetme (sunucu tarafı olasılık), değiştirilemezlik, sonuçlandırma, yetki."""

from __future__ import annotations

import json
import math
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from conftest import Clock, make_staff, member, new_client, use
from coupon_support import NOW, markets, poisson_matrix


async def test_generate_requires_login(
    app: Any, sql: psycopg.Connection[Any], seeded: dict[str, Any]
) -> None:
    async with new_client(app) as c:
        assert (await c.post("/v1/coupons/generate", json={})).status_code == 401


async def test_generate_draft(
    app: Any, sql: psycopg.Connection[Any], seeded: dict[str, Any]
) -> None:
    async with new_client(app) as c:
        await member(c, sql, "kupon@ornek.com")
        r = await c.post(
            "/v1/coupons/generate", json={"date": "2026-11-20", "profile": "low", "size": 2}
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["legs"]) == 2 and len({leg["fixture_id"] for leg in d["legs"]}) == 2
        assert all(leg["probability"] >= 0.70 for leg in d["legs"])
        expected = math.prod(leg["probability"] for leg in d["legs"])
        assert d["joint_probability"] == pytest.approx(expected)
        assert d["monte_carlo"]["converged"] is True and [
            x["n"] for x in d["monte_carlo"]["runs"]
        ] == [10_000, 50_000]
        assert (
            d["odds"] is None and "EV" in d["odds_note"] and "garantisi değildir" in d["disclaimer"]
        )
        r = await c.post(
            "/v1/coupons/generate", json={"date": "2026-11-20", "profile": "low", "size": 6}
        )
        assert r.status_code == 422 and r.json()["code"] == "insufficient_candidates"
        r = await c.post("/v1/coupons/generate", json={"profile": "low", "markets": ["korner"]})
        assert r.json()["code"] == "unknown_market"


async def test_save_recomputes_and_is_immutable(
    app: Any, sql: psycopg.Connection[Any], seeded: dict[str, Any]
) -> None:
    p = seeded["preds"]
    async with new_client(app) as c:
        await member(c, sql, "kupon@ornek.com")
        body = {
            "legs": [
                {"prediction_id": p[0], "market": "1x2", "pick": "home"},
                {"prediction_id": p[0], "market": "total", "pick": "over_2.5"},
                {"prediction_id": p[1], "market": "double_chance", "pick": "1X"},
            ]
        }
        r = await c.post("/v1/coupons", json=body)
        assert r.status_code == 201, r.text
        coupon = r.json()
        legs = coupon["legs"]
        assert [leg["label"] for leg in legs] == ["Maç sonucu: 1", "2.5 Üst", "Çifte şans: 1X"]
        # Aynı maçtaki iki seçim çarpılmaz; ortak dağılımdan hesaplanır.
        naive = legs[0]["probability"] * legs[1]["probability"] * legs[2]["probability"]
        m = poisson_matrix(2.4, 0.5)
        same = sum(m[i][j] for i in range(11) for j in range(11) if i > j and i + j > 2)
        assert coupon["joint_probability"] == pytest.approx(same * legs[2]["probability"])
        assert coupon["joint_probability"] != pytest.approx(naive, abs=1e-3)
        assert coupon["status"] == "pending"

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql.execute(
                "UPDATE coupons SET joint_probability = 0.99 WHERE id = %s", (coupon["id"],)
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql.execute(
                "UPDATE coupon_legs SET probability = 0.99 WHERE coupon_id = %s", (coupon["id"],)
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql.execute("DELETE FROM coupons WHERE id = %s", (coupon["id"],))

        assert (
            await c.post("/v1/coupons", json={"legs": [body["legs"][0], body["legs"][0]]})
        ).json()["code"] == "duplicate_leg"
        assert (
            await c.post(
                "/v1/coupons",
                json={"legs": [{"prediction_id": p[0], "market": "1x2", "pick": "x"}]},
            )
        ).json()["code"] == "unknown_market"
        listing = (await c.get("/v1/coupons")).json()["items"]
        assert [x["id"] for x in listing] == [coupon["id"]]
    async with new_client(app) as other:
        await member(other, sql, "baska@ornek.com")
        assert (await other.get(f"/v1/coupons/{coupon['id']}")).status_code == 404


async def test_stale_prediction_and_kickoff(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, Any]
) -> None:
    p, fx = seeded["preds"], seeded["fixtures"]
    kickoff = sql.execute(
        "SELECT kickoff_at FROM football_fixtures WHERE id=%s", (fx[0],)
    ).fetchone()[0]
    sql.execute(
        "INSERT INTO ml_predictions (fixture_id, model_version_id, created_at, kickoff_at, status, probabilities, reliability,"
        " features, feature_hash, data_snapshot) VALUES (%s,%s,%s,%s,'published',%s,'medium','{}',%s,'{}')",
        (
            fx[0],
            seeded["version"],
            NOW - timedelta(minutes=10),
            kickoff,
            json.dumps(markets(2.0, 0.8)),
            "c" * 64,
        ),
    )
    async with new_client(app) as c:
        await member(c, sql, "kupon@ornek.com")
        r = await c.post(
            "/v1/coupons", json={"legs": [{"prediction_id": p[0], "market": "1x2", "pick": "home"}]}
        )
        assert r.json()["code"] == "stale_prediction"
        clock.advance(hours=3)  # ilk maç başlıyor
        r = await c.post(
            "/v1/coupons", json={"legs": [{"prediction_id": p[1], "market": "1x2", "pick": "home"}]}
        )
        assert r.status_code == 201
        r = await c.post(
            "/v1/coupons",
            json={"legs": [{"prediction_id": p[1] + 100, "market": "1x2", "pick": "home"}]},
        )
        assert r.json()["code"] == "stale_prediction"


async def test_settlement_and_admin(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, Any]
) -> None:
    p, fx = seeded["preds"], seeded["fixtures"]
    async with new_client(app) as c:
        await member(c, sql, "kupon@ornek.com")
        won = (
            await c.post(
                "/v1/coupons",
                json={
                    "legs": [
                        {"prediction_id": p[0], "market": "1x2", "pick": "home"},
                        {"prediction_id": p[1], "market": "btts", "pick": "yes"},
                    ]
                },
            )
        ).json()
        lost = (
            await c.post(
                "/v1/coupons",
                json={"legs": [{"prediction_id": p[0], "market": "total", "pick": "under_1.5"}]},
            )
        ).json()
        void = (
            await c.post(
                "/v1/coupons",
                json={"legs": [{"prediction_id": p[2], "market": "1x2", "pick": "away"}]},
            )
        ).json()

    sql.execute(
        "UPDATE football_fixtures SET status='finished', status_detail='FT', home_goals=3, away_goals=1, ft_home=3, ft_away=1 WHERE id=%s",
        (fx[0],),
    )
    sql.execute("UPDATE football_fixtures SET status='cancelled' WHERE id=%s", (fx[2],))
    analyst = await make_staff(app, sql, clock, "analist@ornek.com", "ANALYST")
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    async with use(analyst.client) as a, use(support.client) as s:
        assert (await s.get("/admin/v1/coupons")).status_code == 200  # SUPPORT: coupons.read
        assert (await s.post("/admin/v1/coupons/settle")).status_code == 403
        assert (await a.post("/admin/v1/coupons/settle")).json() == {"legs": 3, "coupons": 2}
        status = dict(sql.execute("SELECT id, status FROM coupons").fetchall())
        assert status == {won["id"]: "pending", lost["id"]: "lost", void["id"]: "void"}

        sql.execute(
            "UPDATE football_fixtures SET status='finished', status_detail='FT', home_goals=1, away_goals=1, ft_home=1, ft_away=1 WHERE id=%s",
            (fx[1],),
        )
        assert (await a.post("/admin/v1/coupons/settle")).json() == {"legs": 1, "coupons": 1}
        assert (await a.post("/admin/v1/coupons/settle")).json() == {"legs": 0, "coupons": 0}
        summary = (await a.get("/admin/v1/coupons")).json()
        assert summary["counts"] == {"won": 1, "lost": 1, "void": 1}
        assert summary["settled"]["n"] == 2 and summary["settled"]["observed_win_rate"] == 0.5
    assert (
        sql.execute("SELECT status FROM coupons WHERE id=%s", (won["id"],)).fetchone()[0] == "won"
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql.execute("UPDATE coupons SET status='lost' WHERE id=%s", (won["id"],))
    actions = [
        r[0]
        for r in sql.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'coupon%%' OR action LIKE 'admin.coupons%%' ORDER BY id"
        )
    ]
    assert actions.count("coupon.created") == 3 and actions.count("admin.coupons_settled") == 3


async def test_coupon_must_precede_kickoff_db(
    sql: psycopg.Connection[Any], seeded: dict[str, Any]
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        sql.execute(
            "INSERT INTO coupons (created_at, first_kickoff_at, profile, legs_count, joint_probability, evaluation)"
            " VALUES (%s, %s, 'manual', 1, 0.5, '{}')",
            (NOW, NOW - timedelta(minutes=1)),
        )
