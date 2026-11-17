"""Tahmin API'si ve Model Lab (veriler doğrudan SQL ile; ML paketine bağımlı değil)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from conftest import PASSWORD, Clock, make_staff, new_client, use

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PROBS = {
    "1x2": {"home": 0.5, "draw": 0.3, "away": 0.2},
    "double_chance": {"1X": 0.8, "12": 0.7, "X2": 0.5},
    "btts": {"yes": 0.55, "no": 0.45},
}


def _seed(sql: psycopg.Connection[Any]) -> dict[str, int]:
    comp = sql.execute(
        "INSERT INTO football_competitions (provider, external_id, name, fetched_at) VALUES ('test','1','Test Ligi',%s) RETURNING id",
        (NOW,),
    ).fetchone()[0]
    season = sql.execute(
        "INSERT INTO football_seasons (competition_id, year, label) VALUES (%s, 2026, '2026/27') RETURNING id",
        (comp,),
    ).fetchone()[0]
    t1, t2 = (
        sql.execute(
            "INSERT INTO football_teams (provider, external_id, name, fetched_at) VALUES ('test',%s,%s,%s) RETURNING id",
            (e, n, NOW),
        ).fetchone()[0]
        for e, n in (("a", "Takım A"), ("b", "Takım B"))
    )
    fixtures = [
        sql.execute(
            "INSERT INTO football_fixtures (provider, external_id, season_id, kickoff_at, status, home_team_id, away_team_id, fetched_at)"
            " VALUES ('test', %s, %s, %s, 'scheduled', %s, %s, %s) RETURNING id",
            (str(i), season, NOW + timedelta(days=1, hours=i), t1, t2, NOW),
        ).fetchone()[0]
        for i in range(2)
    ]
    return {"competition": comp, "f0": fixtures[0], "f1": fixtures[1]}


def _version(sql: psycopg.Connection[Any], status: str, ll: float, n: int = 300) -> int:
    metrics = {
        "test": {"ensemble": {"n": n, "log_loss": ll, "brier": 0.6, "ece": 0.02, "accuracy": 0.5}}
    }
    return sql.execute(
        "INSERT INTO ml_model_versions (scope_key, scope, status, trained_until, seed, config, components, temperature,"
        " metrics, data_fingerprint, n_rows, artifact) VALUES ('competition:1', '{}', %s, %s, 42, '{}', %s, 1.1, %s, %s, 500, '{}')"
        " RETURNING id",
        (
            status,
            NOW - timedelta(days=1),
            json.dumps({"dixon_coles": 1.0}),
            json.dumps(metrics),
            "a" * 64,
        ),
    ).fetchone()[0]


def _prediction(
    sql: psycopg.Connection[Any],
    fixture: int,
    version: int,
    created: datetime,
    *,
    published: bool = True,
) -> int:
    kickoff = sql.execute(
        "SELECT kickoff_at FROM football_fixtures WHERE id=%s", (fixture,)
    ).fetchone()[0]
    return sql.execute(
        "INSERT INTO ml_predictions (fixture_id, model_version_id, created_at, kickoff_at, status, probabilities, reliability,"
        " abstain_reasons, features, feature_hash, data_snapshot) VALUES (%s,%s,%s,%s,%s,%s,'medium',%s,'{}',%s,'{}') RETURNING id",
        (
            fixture,
            version,
            created,
            kickoff,
            "published" if published else "abstained",
            json.dumps(PROBS) if published else None,
            json.dumps(
                []
                if published
                else [{"code": "insufficient_history", "message": "Yetersiz geçmiş"}]
            ),
            "b" * 64,
        ),
    ).fetchone()[0]


@pytest.fixture
def seeded(sql: psycopg.Connection[Any], clock: Clock) -> dict[str, int]:
    clock.now = NOW
    ids = _seed(sql)
    ids["champion"] = _version(sql, "champion", 0.98)
    ids["challenger"] = _version(sql, "challenger", 0.97)
    _prediction(sql, ids["f0"], ids["champion"], NOW - timedelta(hours=5))
    ids["latest"] = _prediction(sql, ids["f0"], ids["champion"], NOW - timedelta(hours=1))
    ids["abstained"] = _prediction(
        sql, ids["f1"], ids["champion"], NOW - timedelta(hours=1), published=False
    )
    return ids


async def test_fixture_prediction_latest(app: Any, seeded: dict[str, int]) -> None:
    async with new_client(app) as c:
        body = (await c.get(f"/v1/predictions/fixtures/{seeded['f0']}")).json()
        assert body["id"] == seeded["latest"] and body["status"] == "published"
        assert body["probabilities"]["1x2"]["home"] == 0.5
        assert body["reliability"] == {"level": "medium", "label": "Orta"}
        assert "garantisi değildir" in body["disclaimer"]
        abst = (await c.get(f"/v1/predictions/fixtures/{seeded['f1']}")).json()
        assert abst["status"] == "abstained" and abst["probabilities"] is None
        assert abst["abstain_reasons"][0]["code"] == "insufficient_history"
        assert (await c.get("/v1/predictions/fixtures/999999")).status_code == 404


async def test_list_by_turkey_day(app: Any, seeded: dict[str, int]) -> None:
    async with new_client(app) as c:
        body = (await c.get("/v1/predictions", params={"date": "2026-11-21"})).json()
        assert [i["fixture_id"] for i in body["items"]] == [seeded["f0"], seeded["f1"]]
        assert (await c.get("/v1/predictions", params={"date": "2026-11-22"})).json()["items"] == []


async def test_performance_only_from_settled(
    app: Any, sql: psycopg.Connection[Any], seeded: dict[str, int]
) -> None:
    async with new_client(app) as c:
        empty = (await c.get("/v1/predictions/performance")).json()
        assert empty["data_status"] == "no_settled_predictions" and "brier" not in empty
        sql.execute(
            "INSERT INTO ml_prediction_outcomes (prediction_id, settled_at, home_goals, away_goals, outcome, brier, log_loss)"
            " VALUES (%s, %s, 2, 0, 'home', 0.38, 0.693), (%s, %s, 1, 1, 'draw', NULL, NULL)",
            (seeded["latest"], NOW, seeded["abstained"], NOW),
        )
        perf = (await c.get("/v1/predictions/performance")).json()
    assert (
        perf["data_status"] == "ok"
        and perf["settled_published"] == 1
        and perf["settled_abstained"] == 1
    )
    assert perf["brier"] == pytest.approx(0.38) and perf["accuracy"] == 1.0
    assert perf["reliability"][0]["count"] == 1


async def test_model_lab_and_promotion(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, int]
) -> None:
    analyst = await make_staff(app, sql, clock, "analist@ornek.com", "ANALYST")
    support = await make_staff(app, sql, clock, "destek@ornek.com", "SUPPORT")
    async with use(analyst.client) as a, use(support.client) as s:
        assert (await s.get("/admin/v1/models")).status_code == 403
        items = (await a.get("/admin/v1/models")).json()["items"]
        chal = next(i for i in items if i["id"] == seeded["challenger"])
        assert chal["vs_champion"]["log_loss_delta"] == pytest.approx(-0.01)
        detail = (await a.get(f"/admin/v1/models/{seeded['champion']}")).json()
        assert detail["predictions"] == 3 and "artifact" not in detail

        clock.advance(minutes=10)  # yeniden doğrulama süresi doldu
        r = await a.post(f"/admin/v1/models/{seeded['challenger']}/promote")
        assert r.status_code == 403 and r.json()["code"] == "reauth_required"
        await a.post(
            "/admin/v1/auth/reauth", json={"password": PASSWORD, "code": analyst.totp.code()}
        )
        r = await a.post(f"/admin/v1/models/{seeded['challenger']}/promote")
        assert r.status_code == 200 and r.json()["status"] == "champion"
        assert (await a.post(f"/admin/v1/models/{seeded['challenger']}/promote")).status_code == 409
        # Geri alma: eski şampiyon yeniden şampiyon yapılabilir.
        assert (await a.post(f"/admin/v1/models/{seeded['champion']}/promote")).status_code == 200
    statuses = dict(sql.execute("SELECT id, status FROM ml_model_versions").fetchall())
    assert statuses == {seeded["champion"]: "champion", seeded["challenger"]: "retired"}
    details = [
        r[0]
        for r in sql.execute(
            "SELECT details FROM audit_log WHERE action='admin.model_promoted' ORDER BY id"
        )
    ]
    assert details[0]["previous_champion"] == seeded["champion"]


async def test_unevaluated_model_cannot_be_promoted(
    app: Any, sql: psycopg.Connection[Any], clock: Clock, seeded: dict[str, int]
) -> None:
    raw = _version(sql, "challenger", 0.9, n=0)
    analyst = await make_staff(app, sql, clock, "analist@ornek.com", "ANALYST")
    async with use(analyst.client) as a:
        assert (await a.post(f"/admin/v1/models/{raw}/promote")).json()["code"] == "not_evaluated"
