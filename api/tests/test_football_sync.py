"""Senkronizasyon işleri: gerçek PostgreSQL + sahte sağlayıcı HTTP katmanı."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from conftest import Clock
from football_support import FakeApi, api_football_default
from mi_api.football.sync import RunResult

AF = {"football_provider": "api_football", "football_api_key": "test-key"}


async def run(app: Any, job: str, **params: Any) -> RunResult:
    runtime = app.state.football
    service, provider = runtime.service(app.state.services.db)
    try:
        return await service.run(job, params, trigger="cli")  # type: ignore[arg-type]
    finally:
        if provider is not None:
            await provider.aclose()


@pytest.fixture
def api() -> FakeApi:
    return api_football_default()


@pytest.fixture
def af_app(app_factory: Any, api: FakeApi) -> Any:
    return app_factory(football_transport=api.transport, **AF)


async def test_no_provider_skips_without_inventing_data(app: Any, sql: Any) -> None:
    result = await run(app, "fixtures_date", date="2026-11-16")
    assert result.status == "skipped" and "yapılandırılmamış" in (result.message or "")
    assert sql.execute("SELECT count(*) FROM football_fixtures").fetchone()[0] == 0
    row = sql.execute("SELECT job, status, requests FROM football_sync_runs").fetchone()
    assert row == ("fixtures_date", "skipped", 0)


async def test_fixtures_date_upsert_idempotent(af_app: Any, sql: Any, clock: Clock) -> None:
    clock.now = datetime(2026, 11, 16, 23, 0, tzinfo=UTC)
    first = await run(af_app, "fixtures_date", date="2026-11-16")
    assert (first.status, first.items, first.requests) == ("succeeded", 3, 1)
    second = await run(af_app, "fixtures_date", date="2026-11-16")
    assert second.status == "succeeded"
    counts = sql.execute(
        "SELECT (SELECT count(*) FROM football_fixtures), (SELECT count(*) FROM football_teams),"
        " (SELECT count(*) FROM football_competitions), (SELECT count(*) FROM football_seasons),"
        " (SELECT count(*) FROM football_countries), (SELECT count(*) FROM football_venues)"
    ).fetchone()
    assert counts == (3, 4, 2, 2, 1, 1)
    fx = sql.execute(
        "SELECT status, home_goals, away_goals, ht_home, ft_home, provider, fetched_at"
        " FROM football_fixtures WHERE external_id='1001'"
    ).fetchone()
    assert fx[:6] == ("finished", 2, 1, 1, 2, "api_football")
    assert fx[6] == clock.now
    pen = sql.execute(
        "SELECT home_goals, et_home, pen_home, pen_away FROM football_fixtures WHERE external_id='1003'"
    ).fetchone()
    assert pen == (1, 0, 4, 3)
    status = sql.execute(
        "SELECT daily_remaining, minute_remaining, last_success_at FROM football_provider_status"
    ).fetchone()
    assert status[0] == 87 and status[1] == 9 and status[2] is not None


async def test_stale_response_cannot_overwrite_newer(af_app: Any, sql: Any, clock: Clock) -> None:
    await run(af_app, "fixtures_date", date="2026-11-16")
    future = clock.now + timedelta(hours=1)
    sql.execute(
        "UPDATE football_fixtures SET home_goals = 9, fetched_at = %s WHERE external_id = '1001'",
        (future,),
    )
    await run(af_app, "fixtures_date", date="2026-11-16")
    assert (
        sql.execute("SELECT home_goals FROM football_fixtures WHERE external_id='1001'").fetchone()[
            0
        ]
        == 9
    )


async def test_live_skips_without_candidates(af_app: Any, api: FakeApi) -> None:
    result = await run(af_app, "live")
    assert result.status == "skipped" and result.requests == 0 and api.calls == []


async def test_live_updates_and_finalizes_dropped(
    af_app: Any, api: FakeApi, sql: Any, clock: Clock
) -> None:
    await run(af_app, "fixtures_date", date="2026-11-16")
    clock.now = datetime(2026, 11, 16, 23, 40, tzinfo=UTC)
    result = await run(af_app, "live")
    assert result.status == "succeeded"
    assert sql.execute(
        "SELECT status, minute, home_goals, away_goals FROM football_fixtures WHERE external_id='1002'"
    ).fetchone() == ("live", 67, 0, 1)
    # Maç canlı listesinden düştü → tek tek sorgulanıp son skor yazılır.
    api.add("/fixtures", {"live": "all", "timezone": "UTC"}, "live_empty")
    clock.advance(minutes=40)
    result = await run(af_app, "live")
    assert result.requests == 2
    assert sql.execute(
        "SELECT status, home_goals, away_goals FROM football_fixtures WHERE external_id='1002'"
    ).fetchone() == ("finished", 0, 2)


async def test_fixture_details_and_replacement(af_app: Any, api: FakeApi, sql: Any) -> None:
    await run(af_app, "fixtures_date", date="2026-11-16")
    fid_1001 = sql.execute("SELECT id FROM football_fixtures WHERE external_id='1001'").fetchone()[
        0
    ]
    fid_1002 = sql.execute("SELECT id FROM football_fixtures WHERE external_id='1002'").fetchone()[
        0
    ]

    result = await run(af_app, "fixture_details", fixture_id=fid_1001)
    # Bitmiş maç: istatistik + kadro + eksikler denenir; kadro/eksik örneği yok → boş liste (404).
    assert result.status == "succeeded"
    stats = sql.execute(
        "SELECT shots_total, xg, possession_pct, red_cards FROM football_fixture_team_stats ORDER BY shots_total DESC"
    ).fetchall()
    assert [tuple(None if v is None else float(v) for v in r) for r in stats] == [
        (14, 1.85, 58.0, None),
        (8, 0.74, 42.0, 1),
    ]

    result = await run(af_app, "fixture_details", fixture_id=fid_1002)
    assert result.status == "succeeded"
    assert (
        sql.execute(
            "SELECT count(*) FROM football_fixture_team_stats WHERE fixture_id=%s", (fid_1002,)
        ).fetchone()[0]
        == 0
    )
    assert (
        sql.execute(
            "SELECT count(*) FROM football_lineup_players WHERE fixture_id=%s", (fid_1002,)
        ).fetchone()[0]
        == 6
    )
    absences = dict(
        sql.execute("SELECT category, count(*) FROM football_absences GROUP BY 1").fetchall()
    )
    assert absences == {"injury": 2, "suspension": 1}

    # Sağlayıcı listeyi güncelledi: eski satırlar kalmaz.
    api.add(
        "/injuries", {"fixture": "1002"}, {"errors": [], "paging": {"total": 1}, "response": []}
    )
    await run(af_app, "fixture_details", fixture_id=fid_1002)
    assert sql.execute("SELECT count(*) FROM football_absences").fetchone()[0] == 0


async def test_fixture_details_bad_input(af_app: Any) -> None:
    result = await run(af_app, "fixture_details", fixture_id=999999)
    assert result.status == "failed" and "bulunamadı" in (result.message or "")


async def test_upcoming_details_only_for_active_competitions(
    af_app: Any, sql: Any, clock: Clock
) -> None:
    await run(af_app, "fixtures_date", date="2026-11-16")
    clock.now = datetime(2026, 11, 16, 21, 30, tzinfo=UTC)  # 1002 başlamasına 60 dk
    assert (await run(af_app, "upcoming_details")).status == "skipped"
    sql.execute("UPDATE football_competitions SET is_active = true WHERE external_id = '9001'")
    result = await run(af_app, "upcoming_details")
    assert result.status == "succeeded"
    # 1002: kadro + eksikler; 1001 (bitmiş 4,5 saat önce, istatistiksiz): istatistik.
    assert result.requests == 3
    assert sql.execute("SELECT count(*) FROM football_fixture_team_stats").fetchone()[0] == 2


async def test_standings(af_app: Any, sql: Any) -> None:
    await run(af_app, "fixtures_date", date="2026-11-16")
    comp = sql.execute("SELECT id FROM football_competitions WHERE external_id='9001'").fetchone()[
        0
    ]
    result = await run(af_app, "standings", competition_id=comp)
    assert (result.status, result.items) == ("succeeded", 4)
    rows = sql.execute(
        "SELECT rank, points, won + drawn + lost = played FROM football_standings ORDER BY rank"
    ).fetchall()
    assert [r[:2] for r in rows] == [(1, 29), (2, 26), (3, 18), (4, 4)] and all(r[2] for r in rows)
    assert (await run(af_app, "standings_active")).status == "skipped"  # takip edilen lig yok


async def test_season_backfill_paginates(af_app: Any, sql: Any) -> None:
    await run(af_app, "fixtures_date", date="2026-11-16")
    comp = sql.execute("SELECT id FROM football_competitions WHERE external_id='9001'").fetchone()[
        0
    ]
    result = await run(af_app, "season_backfill", competition_id=comp, season=2026)
    assert (result.status, result.items, result.requests) == ("succeeded", 2, 2)


async def test_quota_budget_blocks_low_priority_first(
    app_factory: Any, api: FakeApi, sql: Any
) -> None:
    # Günlük bütçe 2, rezerv %50 → düşük öncelik en fazla 1 istek, yüksek öncelik 2 istek.
    app = app_factory(
        football_transport=api.transport, football_daily_budget=2, football_reserve_pct=50, **AF
    )
    await run(app, "fixtures_date", date="2026-11-16")  # kullanılan: 1
    comp = sql.execute("SELECT id FROM football_competitions WHERE external_id='9001'").fetchone()[
        0
    ]
    low = await run(app, "standings", competition_id=comp)
    assert low.status == "skipped" and low.requests == 0
    assert (
        await run(app, "fixtures_date", date="2026-11-16")
    ).status == "succeeded"  # kullanılan: 2
    blocked = await run(app, "fixtures_date", date="2026-11-16")
    assert (
        blocked.status == "skipped" and "Kota" in (blocked.message or "") and blocked.requests == 0
    )
    assert api.calls.count("/standings?league=9001&season=2026") == 0


async def test_provider_reported_quota_respected(app_factory: Any, api: FakeApi, sql: Any) -> None:
    api.headers["x-ratelimit-requests-remaining"] = "5"
    app = app_factory(football_transport=api.transport, **AF)
    await run(app, "fixtures_date", date="2026-11-16")
    comp = sql.execute("SELECT id FROM football_competitions WHERE external_id='9001'").fetchone()[
        0
    ]
    # Sağlayıcı 5 hak kaldı diyor; düşük öncelik %20 rezerve (20) giremez.
    assert (await run(app, "standings", competition_id=comp)).status == "skipped"


async def test_provider_error_recorded(app_factory: Any, sql: Any) -> None:
    api = FakeApi()
    api.add("/fixtures", {"date": "2026-11-16", "timezone": "UTC"}, "error_token")
    app = app_factory(football_transport=api.transport, **AF)
    result = await run(app, "fixtures_date", date="2026-11-16")
    assert result.status == "failed"
    row = sql.execute("SELECT last_error, last_success_at FROM football_provider_status").fetchone()
    assert "Missing application key" in row[0] and row[1] is None


async def test_football_data_details_not_supported(app_factory: Any, sql: Any) -> None:
    api = FakeApi("football_data", headers={})
    api.add("/matches", {"dateFrom": "2026-11-16", "dateTo": "2026-11-17"}, "matches_date")
    app = app_factory(
        football_transport=api.transport, football_provider="football_data", football_api_key="k"
    )
    assert (await run(app, "fixtures_date", date="2026-11-16")).items == 2
    fid = sql.execute("SELECT id FROM football_fixtures WHERE external_id='7001'").fetchone()[0]
    result = await run(app, "fixture_details", fixture_id=fid)
    assert result.status == "succeeded" and result.requests == 0
    assert "desteklenmiyor" in (result.message or "")
