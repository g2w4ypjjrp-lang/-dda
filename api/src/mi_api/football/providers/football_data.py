"""football-data.org (v4) uyarlayıcısı.

Belge: https://docs.football-data.org/general/v4/ — kimlik ``X-Auth-Token`` başlığıyla. Dakikalık
kota başlığı ``X-Requests-Available-Minute``. Ücretsiz katman ticari kullanım için uygun değildir
ve takım istatistiği, kadro, sakatlık sunmaz; bu veri türleri ``CapabilityNotSupported`` döner.

Skor alanları: ``fullTime`` maçın nihai skorudur. ``duration`` ``REGULAR`` değilse
``regularTime``, ``extraTime`` ve ``penalties`` ayrıca verilir; penaltılar ``goals``'a katılmaz.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Final

import httpx

from mi_api.football.providers.base import (
    AbsenceData,
    BeforeRequest,
    Capability,
    CapabilityNotSupported,
    CompetitionData,
    CountryData,
    FixtureData,
    FixtureStatus,
    HttpProvider,
    LineupData,
    ProviderError,
    QuotaInfo,
    QuotaObserver,
    Score,
    SeasonData,
    StandingData,
    TeamData,
    TeamStatsData,
    as_int,
    header_int,
    parse_utc,
)

BASE_URL = "https://api.football-data.org/v4"

STATUS: Final[dict[str, FixtureStatus]] = {
    "SCHEDULED": "scheduled", "TIMED": "scheduled",
    "IN_PLAY": "live", "LIVE": "live", "PAUSED": "halftime",
    "FINISHED": "finished", "AWARDED": "awarded",
    "POSTPONED": "postponed", "SUSPENDED": "suspended", "CANCELLED": "cancelled",
}  # fmt: skip


def _score(obj: dict[str, Any] | None) -> Score:
    obj = obj or {}
    return Score(as_int(obj.get("home")), as_int(obj.get("away")))


def _add(a: Score, b: Score) -> Score:
    if a.home is None or a.away is None:
        return Score()
    return Score(a.home + (b.home or 0), a.away + (b.away or 0))


def _team(obj: dict[str, Any]) -> TeamData:
    return TeamData(
        external_id=str(obj["id"]),
        name=str(obj.get("name") or obj.get("shortName") or obj["id"]),
        short_name=obj.get("shortName"),
        code=obj.get("tla"),
        logo_url=obj.get("crest"),
    )


class FootballDataProvider(HttpProvider):
    name = "football_data"
    capabilities: frozenset[Capability] = frozenset({"fixtures", "live", "standings"})

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        before_request: BeforeRequest | None = None,
        on_quota: QuotaObserver | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            headers={"X-Auth-Token": api_key, "Accept": "application/json"},
            transport=transport,
            before_request=before_request,
            on_quota=on_quota,
        )

    def quota_from(self, headers: httpx.Headers) -> QuotaInfo | None:
        remaining = header_int(headers, "x-requests-available-minute")
        return QuotaInfo(minute_remaining=remaining) if remaining is not None else None

    @staticmethod
    def parse_match(item: dict[str, Any], competition: dict[str, Any] | None = None) -> FixtureData:
        comp = item.get("competition") or competition
        if not comp:
            raise ProviderError("football_data: maçta lig bilgisi yok")
        raw_status = str(item.get("status") or "")
        status = STATUS.get(raw_status)
        if status is None:
            raise ProviderError(f"football_data: bilinmeyen maç durumu {raw_status!r}")
        kickoff = parse_utc(item.get("utcDate"))
        if kickoff is None:
            raise ProviderError("football_data: maç zamanı yok")
        season = item.get("season") or {}
        start = season.get("startDate")
        end = season.get("endDate")
        year = int(start[:4]) if start else kickoff.year
        area = item.get("area") or {}
        score = item.get("score") or {}
        duration = score.get("duration") or "REGULAR"
        full = _score(score.get("fullTime"))
        if duration == "REGULAR":
            fulltime, extratime, penalties, goals = full, Score(), Score(), full
        else:
            fulltime = _score(score.get("regularTime"))
            extratime = _score(score.get("extraTime"))
            penalties = _score(score.get("penalties"))
            goals = _add(fulltime, extratime)
        referee = next(
            (r.get("name") for r in item.get("referees") or [] if r.get("type") == "REFEREE"), None
        )
        stage = item.get("stage")
        matchday = item.get("matchday")
        return FixtureData(
            external_id=str(item["id"]),
            competition=CompetitionData(
                external_id=str(comp["id"]),
                name=str(comp.get("name") or comp.get("code") or comp["id"]),
                type="cup" if comp.get("type") == "CUP" else "league",
                country=CountryData(
                    name=area["name"], code=area.get("code"), flag_url=area.get("flag")
                )
                if area.get("name")
                else None,
                logo_url=comp.get("emblem"),
            ),
            season=SeasonData(
                year=year,
                label=f"{year}/{(year + 1) % 100:02d}",
                start_date=date.fromisoformat(start) if start else None,
                end_date=date.fromisoformat(end) if end else None,
            ),
            kickoff_at=kickoff,
            status=status,
            status_detail=raw_status,
            minute=as_int(item.get("minute")),
            home=_team(item["homeTeam"]),
            away=_team(item["awayTeam"]),
            round=f"Matchday {matchday}" if matchday else stage,
            referee=referee,
            goals=goals,
            halftime=_score(score.get("halfTime")),
            fulltime=fulltime,
            extratime=extratime,
            penalties=penalties,
            source_updated_at=parse_utc(item.get("lastUpdated")),
        )

    async def _matches(self, path: str, params: dict[str, Any]) -> list[FixtureData]:
        body = await self.get_json(path, params)
        if body is None:
            return []
        competition = body.get("competition")
        return [self.parse_match(m, competition) for m in body.get("matches") or []]

    async def fixtures_by_date(self, day: date) -> list[FixtureData]:
        # v4'te dateTo dahildir; tek günü sorgulamak için iki gün istenir ve UTC güne göre süzülür.
        matches = await self._matches(
            "/matches",
            {"dateFrom": day.isoformat(), "dateTo": (day + timedelta(days=1)).isoformat()},
        )
        return [m for m in matches if m.kickoff_at.date() == day]

    async def live_fixtures(self) -> list[FixtureData]:
        return await self._matches("/matches", {"status": "LIVE"})

    async def fixture(self, external_id: str) -> FixtureData | None:
        body = await self.get_json(f"/matches/{external_id}")
        return self.parse_match(body) if body else None

    async def season_fixtures(self, competition_id: str, season: int) -> list[FixtureData]:
        return await self._matches(f"/competitions/{competition_id}/matches", {"season": season})

    async def standings(self, competition_id: str, season: int) -> list[StandingData]:
        body = await self.get_json(f"/competitions/{competition_id}/standings", {"season": season})
        rows: list[StandingData] = []
        for block in (body or {}).get("standings") or []:
            if block.get("type") != "TOTAL":
                continue
            for entry in block.get("table") or []:
                rows.append(
                    StandingData(
                        team=_team(entry["team"]),
                        rank=int(entry["position"]),
                        played=int(entry["playedGames"]),
                        won=int(entry["won"]),
                        drawn=int(entry["draw"]),
                        lost=int(entry["lost"]),
                        goals_for=int(entry["goalsFor"]),
                        goals_against=int(entry["goalsAgainst"]),
                        points=int(entry["points"]),
                        group=str(block.get("group") or ""),
                        form=(entry.get("form") or "").replace(",", "") or None,
                    )
                )
        return rows

    async def team_stats(self, fixture_id: str) -> list[TeamStatsData]:
        raise CapabilityNotSupported("football_data: takım maç istatistiği sunmuyor")

    async def lineups(self, fixture_id: str) -> list[LineupData]:
        raise CapabilityNotSupported("football_data: kadro sunmuyor")

    async def absences(self, fixture_id: str) -> list[AbsenceData]:
        raise CapabilityNotSupported("football_data: sakatlık/ceza sunmuyor")
