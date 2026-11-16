"""Futbol API'si: Türkiye günü, tazelik, maç detayı, puan durumu, yönetim uçları ve yetkiler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from conftest import Clock, make_staff, new_client, use
from football_support import FakeApi, api_football_default
from test_football_sync import AF, run


@pytest.fixture
def api() -> FakeApi:
    return api_football_default()


@pytest.fixture
def af_app(app_factory: Any, api: FakeApi) -> Any:
    return app_factory(football_transport=api.transport, **AF)


@pytest.fixture
async def loaded(af_app: Any, sql: Any, clock: Clock) -> Any:
    clock.now = datetime(2026, 11, 16, 20, 0, tzinfo=UTC)
    await run(af_app, "fixtures_date", date="2026-11-16")
    return af_app


async def test_no_provider_status(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/football/fixtures", params={"date": "2026-11-16"})).json()
    assert body["items"] == [] and body["data_status"] == "no_provider"
    assert (await client.get("/v1/football/status")).json()["provider_label"] == "Yapılandırılmamış"


async def test_fixtures_grouped_by_turkey_date(loaded: Any) -> None:
    async with new_client(loaded) as c:
        day16 = (await c.get("/v1/football/fixtures", params={"date": "2026-11-16"})).json()
        day17 = (await c.get("/v1/football/fixtures", params={"date": "2026-11-17"})).json()
    # 1002: 16 Kasım 22:30 UTC = 17 Kasım 01:30 Türkiye saati.
    assert [i["home"]["name"] for i in day16["items"]] == ["Örnek FK", "Test Spor"]
    assert [i["home"]["name"] for i in day17["items"]] == ["Deneme SK"]
    match = day17["items"][0]
    assert match["kickoff_local"] == "2026-11-17T01:30:00+03:00"
    assert match["score"]["current"] is None and match["status"] == "scheduled"
    assert day16["data_status"] == "ok" and day16["last_successful_sync_at"]
    first = day16["items"][0]
    assert first["score"]["current"] == {"home": 2, "away": 1}
    assert first["source"]["provider_label"].startswith("API-Football")
    assert first["freshness"]["stale"] is False


async def test_default_date_is_today_in_turkey(loaded: Any, clock: Clock) -> None:
    clock.now = datetime(2026, 11, 16, 22, 15, tzinfo=UTC)  # Türkiye'de 17 Kasım 01:15
    async with new_client(loaded) as c:
        body = (await c.get("/v1/football/fixtures")).json()
    assert body["date"] == "2026-11-17"


async def test_filters(loaded: Any, sql: Any) -> None:
    cup = sql.execute("SELECT id FROM football_competitions WHERE external_id='9002'").fetchone()[0]
    async with new_client(loaded) as c:
        by_comp = (
            await c.get(
                "/v1/football/fixtures", params={"date": "2026-11-16", "competition_id": cup}
            )
        ).json()
        by_status = (
            await c.get(
                "/v1/football/fixtures", params={"date": "2026-11-16", "status": "finished"}
            )
        ).json()
        bad = await c.get("/v1/football/fixtures", params={"status": "bitti"})
    assert len(by_comp["items"]) == 1 and by_comp["items"][0]["score"]["penalties"] == {
        "home": 4,
        "away": 3,
    }
    assert len(by_status["items"]) == 2
    assert bad.status_code == 422


async def test_stale_scheduled_match_flagged(loaded: Any, clock: Clock) -> None:
    clock.now = datetime(
        2026, 11, 16, 22, 40, tzinfo=UTC
    )  # başlama saati geçti, veri 2 saat 40 dk eski
    async with new_client(loaded) as c:
        item = (await c.get("/v1/football/fixtures", params={"date": "2026-11-17"})).json()[
            "items"
        ][0]
    assert item["freshness"]["stale"] is True and item["freshness"]["age_s"] == 9600


async def test_fixture_detail(loaded: Any, sql: Any, clock: Clock) -> None:
    f1001 = sql.execute("SELECT id FROM football_fixtures WHERE external_id='1001'").fetchone()[0]
    f1002 = sql.execute("SELECT id FROM football_fixtures WHERE external_id='1002'").fetchone()[0]
    async with new_client(loaded) as c:
        before = (await c.get(f"/v1/football/fixtures/{f1001}")).json()
        assert before["team_stats"] == {}
        assert {i["code"] for i in before["completeness"]["issues"]} == {"no_team_stats"}
        assert before["completeness"]["score"] == 80

        await run(loaded, "fixture_details", fixture_id=f1001)
        await run(loaded, "fixture_details", fixture_id=f1002)
        detail = (await c.get(f"/v1/football/fixtures/{f1001}")).json()
        assert detail["team_stats"]["home"]["xg"] == 1.85
        assert detail["team_stats"]["away"]["possession_pct"] == 42.0
        assert detail["completeness"] == {"score": 100, "issues": []}
        assert detail["venue"] == {"name": "Örnek Stadı", "city": "İstanbul"}

        upcoming = (await c.get(f"/v1/football/fixtures/{f1002}")).json()
        assert upcoming["lineups"]["home"]["formation"] == "4-3-3"
        assert [p["name"] for p in upcoming["lineups"]["home"]["players"] if p["starter"]] == [
            "Kaleci Bir",
            "Defans İki",
            "Forvet Üç",
        ]
        assert {a["player"]: a["category"] for a in upcoming["absences"]} == {
            "Forvet Üç": "injury",
            "Stoper Yedi": "suspension",
            "Kanat Sekiz": "injury",
        }
        assert (await c.get("/v1/football/fixtures/999999")).status_code == 404


async def test_standings_endpoint(loaded: Any, sql: Any) -> None:
    comp = sql.execute("SELECT id FROM football_competitions WHERE external_id='9001'").fetchone()[
        0
    ]
    async with new_client(loaded) as c:
        empty = (await c.get(f"/v1/football/competitions/{comp}/standings")).json()
        assert empty["groups"] == []
        await run(loaded, "standings", competition_id=comp)
        table = (await c.get(f"/v1/football/competitions/{comp}/standings")).json()
    assert table["season"]["label"] == "2026/27"
    rows = table["groups"][0]["table"]
    assert rows[0]["team"]["name"] == "Örnek FK" and rows[0]["goal_diff"] == 16
    assert table["fetched_at"]


async def test_competitions_listing(loaded: Any, sql: Any) -> None:
    async with new_client(loaded) as c:
        assert (await c.get("/v1/football/competitions")).json()["items"] == []
        everything = (
            await c.get("/v1/football/competitions", params={"active_only": "false"})
        ).json()["items"]
    assert {i["name"] for i in everything} == {"Örnek Lig", "Örnek Kupa"}
    assert everything[0]["country"] == "Türkiye"


async def test_admin_sync_and_tracking(loaded: Any, sql: Any, clock: Clock) -> None:
    ops = await make_staff(loaded, sql, clock, "operasyon@ornek.com", "OPERATIONS_MANAGER")
    support = await make_staff(loaded, sql, clock, "destek@ornek.com", "SUPPORT")
    analyst = await make_staff(loaded, sql, clock, "analist@ornek.com", "ANALYST")
    comp = sql.execute("SELECT id FROM football_competitions WHERE external_id='9001'").fetchone()[
        0
    ]
    async with use(ops.client) as o, use(support.client) as s, use(analyst.client) as a:
        assert (await s.get("/admin/v1/football/status")).status_code == 403
        status = (await a.get("/admin/v1/football/status")).json()
        assert status["provider"] == "api_football" and "xg" in status["capabilities"]
        assert status["provider_reported"]["daily_remaining"] == 87
        assert status["budget"]["used_today"] == 1
        assert (await a.post("/admin/v1/football/sync", json={"job": "live"})).status_code == 403

        r = await o.post(
            "/admin/v1/football/sync", json={"job": "standings", "competition_id": comp}
        )
        assert r.status_code == 200 and r.json()["status"] == "succeeded" and r.json()["items"] == 4
        r = await o.post(
            "/admin/v1/football/sync", json={"job": "fixtures_date", "date": "2026-11-16"}
        )
        assert r.json()["status"] == "succeeded"
        assert (await o.post("/admin/v1/football/sync", json={"job": "yok"})).status_code == 422

        runs = (await o.get("/admin/v1/football/sync-runs", params={"job": "standings"})).json()[
            "items"
        ]
        assert runs[0]["trigger"] == "admin" and runs[0]["requests"] == 1

        r = await o.patch(f"/admin/v1/football/competitions/{comp}", json={"is_active": True})
        assert r.json()["is_active"] is True
    async with new_client(loaded) as c:
        assert [i["name"] for i in (await c.get("/v1/football/competitions")).json()["items"]] == [
            "Örnek Lig"
        ]
    actions = [
        r[0]
        for r in sql.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'admin.%%football%%' OR action LIKE 'admin.competition%%' ORDER BY id"
        )
    ]
    assert actions == [
        "admin.football_sync",
        "admin.football_sync",
        "admin.competition_tracking_changed",
    ]


async def test_freshness_rules() -> None:
    from mi_api.football.quality import freshness

    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    assert freshness("live", now, now - timedelta(minutes=4), now)["stale"] is True
    assert freshness("live", now, now - timedelta(minutes=2), now)["stale"] is False
    assert (
        freshness("scheduled", now + timedelta(days=3), now - timedelta(hours=12), now)["stale"]
        is False
    )
    assert (
        freshness("scheduled", now + timedelta(hours=3), now - timedelta(hours=2), now)["stale"]
        is True
    )
    assert (
        freshness("finished", now - timedelta(days=30), now - timedelta(days=29), now)["stale"]
        is False
    )
