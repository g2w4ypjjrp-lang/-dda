"""Sağlayıcı uyarlayıcıları: ayrıştırma, durum eşleme, kota başlıkları, hatalar (veritabanı yok)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from football_support import FakeApi, api_football_default
from mi_api.football.providers import base
from mi_api.football.providers.api_football import ApiFootballProvider
from mi_api.football.providers.base import (
    CapabilityNotSupported,
    ProviderError,
    QuotaExceeded,
    QuotaInfo,
)
from mi_api.football.providers.football_data import FootballDataProvider


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(base.asyncio, "sleep", instant)


def af(api: FakeApi, **kw: Any) -> ApiFootballProvider:
    return ApiFootballProvider("test-key", transport=api.transport, **kw)


async def test_api_football_fixtures_by_date() -> None:
    api = api_football_default()
    seen: list[QuotaInfo] = []

    async def on_quota(info: QuotaInfo) -> None:
        seen.append(info)

    provider = af(api, on_quota=on_quota)
    fixtures = {f.external_id: f for f in await provider.fixtures_by_date(date(2026, 11, 16))}
    assert set(fixtures) == {"1001", "1002", "1003"}

    finished = fixtures["1001"]
    assert finished.status == "finished" and finished.status_detail == "FT"
    assert finished.kickoff_at == datetime(2026, 11, 16, 17, 0, tzinfo=UTC)
    assert (finished.goals.home, finished.goals.away) == (2, 1)
    assert (finished.halftime.home, finished.halftime.away) == (1, 0)
    assert finished.competition.name == "Örnek Lig" and finished.competition.country
    assert finished.season.year == 2026 and finished.season.label == "2026/27"
    assert finished.venue and finished.venue.city == "İstanbul"

    upcoming = fixtures["1002"]
    assert upcoming.status == "scheduled" and upcoming.goals.home is None

    shootout = fixtures["1003"]
    assert shootout.competition.type == "cup" and shootout.venue is None
    assert (shootout.goals.home, shootout.penalties.home, shootout.penalties.away) == (1, 4, 3)

    assert provider.requests_made == 1
    assert seen == [QuotaInfo(100, 87, 10, 9)]
    await provider.aclose()


async def test_api_football_pagination() -> None:
    provider = af(api_football_default())
    fixtures = await provider.season_fixtures("9001", 2026)
    assert [f.external_id for f in fixtures] == ["1001", "1002"]
    assert provider.requests_made == 2


async def test_api_football_details() -> None:
    provider = af(api_football_default())
    stats = {s.team.external_id: s for s in await provider.team_stats("1001")}
    home = stats["501"]
    assert home.shots_total == 14 and home.shots_on_target == 6
    assert home.possession_pct == Decimal("58") and home.xg == Decimal("1.85")
    assert home.red_cards is None  # sağlayıcı null verdi; 0 uydurulmaz
    assert stats["502"].red_cards == 1

    lineups = await provider.lineups("1002")
    assert lineups[0].formation == "4-3-3" and lineups[0].coach_name == "Teknik Direktör A"
    starters = [e for e in lineups[0].players if e.is_starter]
    assert len(starters) == 3 and starters[0].grid == "1:1"

    absences = {a.player.name: a for a in await provider.absences("1002")}
    assert absences["Forvet Üç"].status == "questionable"
    assert absences["Forvet Üç"].category == "injury"  # "Tired" ceza sayılmaz
    assert absences["Stoper Yedi"].category == "suspension"
    assert (
        absences["Kanat Sekiz"].category == "injury" and absences["Kanat Sekiz"].status == "missing"
    )

    standings = await provider.standings("9001", 2026)
    assert [s.rank for s in standings] == [1, 2, 3, 4]
    assert standings[0].points == 29 and standings[0].form == "WWDWL"


@pytest.mark.parametrize(
    ("sample_name", "error"),
    [("error_token", ProviderError), ("error_requests", QuotaExceeded)],
)
async def test_api_football_error_envelope(sample_name: str, error: type[Exception]) -> None:
    api = FakeApi()
    api.add("/fixtures", {"date": "2026-11-16", "timezone": "UTC"}, sample_name)
    with pytest.raises(error):
        await af(api).fixtures_by_date(date(2026, 11, 16))


async def test_http_errors_and_retries() -> None:
    attempts = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(502)
        return httpx.Response(200, json={"errors": [], "paging": {"total": 1}, "response": []})

    provider = ApiFootballProvider("k", transport=httpx.MockTransport(flaky))
    assert await provider.live_fixtures() == []
    assert attempts["n"] == 3 and provider.requests_made == 3

    for status, error in ((401, ProviderError), (429, QuotaExceeded), (500, ProviderError)):
        p = ApiFootballProvider(
            "k", transport=httpx.MockTransport(lambda _r, s=status: httpx.Response(s))
        )
        with pytest.raises(error):
            await p.live_fixtures()


async def test_before_request_hook_blocks() -> None:
    async def deny() -> None:
        raise QuotaExceeded("bütçe yok")

    api = api_football_default()
    with pytest.raises(QuotaExceeded):
        await af(api, before_request=deny).live_fixtures()
    assert api.calls == []  # istek gönderilmedi


async def test_unknown_status_rejected() -> None:
    body = api_football_default().routes
    item = next(iter(body.values()))[1]["response"][0]
    item["fixture"]["status"]["short"] = "XYZ"
    with pytest.raises(ProviderError, match="bilinmeyen"):
        ApiFootballProvider.parse_fixture(item)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ProviderError):
        base.parse_utc("2026-11-16T17:00:00")


async def test_football_data_matches_and_standings() -> None:
    api = FakeApi("football_data", headers={"X-Requests-Available-Minute": "8"})
    api.add("/matches", {"dateFrom": "2026-11-16", "dateTo": "2026-11-17"}, "matches_date")
    api.add("/competitions/2001/standings", {"season": "2026"}, "standings")
    seen: list[QuotaInfo] = []

    async def on_quota(info: QuotaInfo) -> None:
        seen.append(info)

    provider = FootballDataProvider("k", transport=api.transport, on_quota=on_quota)
    matches = {m.external_id: m for m in await provider.fixtures_by_date(date(2026, 11, 16))}
    assert set(matches) == {"7001", "7002"}  # 17 Kasım maçı süzüldü
    regular = matches["7001"]
    assert regular.status == "finished" and (regular.goals.home, regular.goals.away) == (2, 0)
    assert regular.referee == "Hakem Kurgu" and regular.round == "Matchday 12"
    assert regular.season.start_date == date(2026, 8, 7)
    shootout = matches["7002"]
    assert (shootout.goals.home, shootout.goals.away) == (1, 1)  # penaltılar skora katılmaz
    assert (shootout.penalties.home, shootout.penalties.away) == (3, 4)
    assert shootout.round == "LAST_16"
    assert seen[0] == QuotaInfo(minute_remaining=8)

    table = await provider.standings("2001", 2026)
    assert [r.team.name for r in table] == [
        "Kurgu Spor Kulübü",
        "Örnekköy SK",
    ]  # HOME tablosu alınmaz
    assert table[0].form == "WWDWW"

    for call in (provider.team_stats, provider.lineups, provider.absences):
        with pytest.raises(CapabilityNotSupported):
            await call("7001")
