"""API-Football (api-sports.io, v3) uyarlayıcısı.

Belge: https://www.api-football.com/documentation-v3 — kimlik ``x-apisports-key`` başlığıyla.
Yanıt zarfı: ``{"get", "parameters", "errors", "results", "paging", "response"}``. ``errors``
boş değilse istek başarısızdır (ör. ``{"token": ...}``, ``{"requests": ...}`` kota).

Kota başlıkları: ``x-ratelimit-requests-limit`` / ``-remaining`` (günlük),
``X-RateLimit-Limit`` / ``X-RateLimit-Remaining`` (dakikalık).

Not: Biçim, sağlayıcının belgesine göre yazıldı ve belge biçimindeki örnek yanıtlarla test
ediliyor; gerçek API anahtarıyla doğrulama M-G1 onayından sonra yapılacak.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Final, Literal

import httpx

from mi_api.football.providers.base import (
    AbsenceData,
    BeforeRequest,
    Capability,
    CompetitionData,
    CountryData,
    FixtureData,
    FixtureStatus,
    HttpProvider,
    LineupData,
    LineupEntry,
    PlayerData,
    ProviderError,
    QuotaExceeded,
    QuotaInfo,
    QuotaObserver,
    Score,
    SeasonData,
    StandingData,
    TeamData,
    TeamStatsData,
    VenueData,
    as_decimal,
    as_int,
    header_int,
    parse_utc,
)

BASE_URL = "https://v3.football.api-sports.io"

STATUS: Final[dict[str, FixtureStatus]] = {
    "TBD": "tbd", "NS": "scheduled",
    "1H": "live", "2H": "live", "ET": "live", "BT": "live", "P": "live", "LIVE": "live",
    "HT": "halftime",
    "FT": "finished", "AET": "finished", "PEN": "finished",
    "PST": "postponed", "SUSP": "suspended", "INT": "suspended",
    "CANC": "cancelled", "ABD": "abandoned", "AWD": "awarded", "WO": "awarded",
}  # fmt: skip

STAT_FIELDS: Final[dict[str, str]] = {
    "Total Shots": "shots_total",
    "Shots on Goal": "shots_on_target",
    "Ball Possession": "possession_pct",
    "Corner Kicks": "corners",
    "Fouls": "fouls",
    "Yellow Cards": "yellow_cards",
    "Red Cards": "red_cards",
    "Offsides": "offsides",
    "Total passes": "passes_total",
    "Passes accurate": "passes_accurate",
    "Goalkeeper Saves": "goalkeeper_saves",
    "expected_goals": "xg",
}
DECIMAL_FIELDS: Final = frozenset({"possession_pct", "xg"})
# Cezalar: "Suspended", "Red Card", "Yellow Cards" (kelime sınırıyla; "Tired" eşleşmez).
_SUSPENSION: Final = re.compile(r"\b(suspen\w*|red card|yellow cards?)\b", re.IGNORECASE)


def _score(obj: dict[str, Any] | None) -> Score:
    obj = obj or {}
    return Score(as_int(obj.get("home")), as_int(obj.get("away")))


def _team(obj: dict[str, Any]) -> TeamData:
    return TeamData(external_id=str(obj["id"]), name=str(obj["name"]), logo_url=obj.get("logo"))


def _player(obj: dict[str, Any]) -> PlayerData:
    return PlayerData(external_id=str(obj["id"]), name=str(obj["name"]), position=obj.get("pos"))


class ApiFootballProvider(HttpProvider):
    name = "api_football"
    capabilities: frozenset[Capability] = frozenset(
        {"fixtures", "live", "standings", "team_stats", "xg", "lineups", "absences"}
    )

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
            headers={"x-apisports-key": api_key, "Accept": "application/json"},
            transport=transport,
            before_request=before_request,
            on_quota=on_quota,
        )

    def quota_from(self, headers: httpx.Headers) -> QuotaInfo | None:
        info = QuotaInfo(
            daily_limit=header_int(headers, "x-ratelimit-requests-limit"),
            daily_remaining=header_int(headers, "x-ratelimit-requests-remaining"),
            minute_limit=header_int(headers, "x-ratelimit-limit"),
            minute_remaining=header_int(headers, "x-ratelimit-remaining"),
        )
        return info if any(v is not None for v in vars(info).values()) else None

    async def _get(self, path: str, params: dict[str, Any]) -> list[Any]:
        """Sayfalı uç noktalarda tüm sayfaları toplar."""
        items: list[Any] = []
        page = 1
        while True:
            query = dict(params)
            if page > 1:
                query["page"] = page
            body = await self.get_json(path, query)
            if body is None:
                return items
            errors = body.get("errors")
            if errors:
                text = str(errors)
                if isinstance(errors, dict) and ("requests" in errors or "rateLimit" in errors):
                    raise QuotaExceeded(f"api_football: {text}")
                raise ProviderError(f"api_football: {text}")
            items.extend(body.get("response") or [])
            paging = body.get("paging") or {}
            total = as_int(paging.get("total")) or 1
            if page >= total:
                return items
            page += 1

    # --- Dönüştürücüler ---------------------------------------------------------------------

    @staticmethod
    def parse_fixture(item: dict[str, Any]) -> FixtureData:
        fx, league, teams = item["fixture"], item["league"], item["teams"]
        status_short = str((fx.get("status") or {}).get("short") or "TBD")
        status = STATUS.get(status_short)
        if status is None:
            raise ProviderError(f"api_football: bilinmeyen maç durumu {status_short!r}")
        kickoff = parse_utc(fx.get("date"))
        if kickoff is None:
            raise ProviderError("api_football: maç zamanı yok")
        venue = fx.get("venue") or {}
        score = item.get("score") or {}
        year = int(league["season"])
        country = league.get("country")
        return FixtureData(
            external_id=str(fx["id"]),
            competition=CompetitionData(
                external_id=str(league["id"]),
                name=str(league["name"]),
                type="cup" if str(league.get("type", "")).lower() == "cup" else "league",
                country=CountryData(name=country, flag_url=league.get("flag")) if country else None,
                logo_url=league.get("logo"),
            ),
            season=SeasonData(year=year, label=f"{year}/{(year + 1) % 100:02d}"),
            kickoff_at=kickoff,
            status=status,
            status_detail=status_short,
            minute=as_int((fx.get("status") or {}).get("elapsed")),
            home=_team(teams["home"]),
            away=_team(teams["away"]),
            round=league.get("round"),
            venue=VenueData(str(venue["id"]), str(venue.get("name") or ""), venue.get("city"))
            if venue.get("id") and venue.get("name")
            else None,
            referee=fx.get("referee"),
            goals=_score(item.get("goals")),
            halftime=_score(score.get("halftime")),
            fulltime=_score(score.get("fulltime")),
            extratime=_score(score.get("extratime")),
            penalties=_score(score.get("penalty")),
        )

    # --- Uç noktalar ------------------------------------------------------------------------

    async def fixtures_by_date(self, day: date) -> list[FixtureData]:
        items = await self._get("/fixtures", {"date": day.isoformat(), "timezone": "UTC"})
        return [self.parse_fixture(i) for i in items]

    async def live_fixtures(self) -> list[FixtureData]:
        items = await self._get("/fixtures", {"live": "all", "timezone": "UTC"})
        return [self.parse_fixture(i) for i in items]

    async def fixture(self, external_id: str) -> FixtureData | None:
        items = await self._get("/fixtures", {"id": external_id, "timezone": "UTC"})
        return self.parse_fixture(items[0]) if items else None

    async def season_fixtures(self, competition_id: str, season: int) -> list[FixtureData]:
        items = await self._get(
            "/fixtures", {"league": competition_id, "season": season, "timezone": "UTC"}
        )
        return [self.parse_fixture(i) for i in items]

    async def standings(self, competition_id: str, season: int) -> list[StandingData]:
        items = await self._get("/standings", {"league": competition_id, "season": season})
        rows: list[StandingData] = []
        for item in items:
            for group in item.get("league", {}).get("standings") or []:
                for entry in group:
                    totals = entry.get("all") or {}
                    goals = totals.get("goals") or {}
                    rows.append(
                        StandingData(
                            team=_team(entry["team"]),
                            rank=int(entry["rank"]),
                            played=int(totals.get("played") or 0),
                            won=int(totals.get("win") or 0),
                            drawn=int(totals.get("draw") or 0),
                            lost=int(totals.get("lose") or 0),
                            goals_for=int(goals.get("for") or 0),
                            goals_against=int(goals.get("against") or 0),
                            points=int(entry.get("points") or 0),
                            group=str(entry.get("group") or ""),
                            form=entry.get("form"),
                        )
                    )
        return rows

    async def team_stats(self, fixture_id: str) -> list[TeamStatsData]:
        items = await self._get("/fixtures/statistics", {"fixture": fixture_id})
        result: list[TeamStatsData] = []
        for item in items:
            values: dict[str, Any] = {}
            for stat in item.get("statistics") or []:
                field_name = STAT_FIELDS.get(str(stat.get("type")))
                if field_name is None:
                    continue
                raw = stat.get("value")
                values[field_name] = (
                    as_decimal(raw) if field_name in DECIMAL_FIELDS else as_int(raw)
                )
            result.append(TeamStatsData(team=_team(item["team"]), **values))
        return result

    async def lineups(self, fixture_id: str) -> list[LineupData]:
        items = await self._get("/fixtures/lineups", {"fixture": fixture_id})
        result: list[LineupData] = []
        for item in items:
            entries: list[LineupEntry] = []
            for key, starter in (("startXI", True), ("substitutes", False)):
                for row in item.get(key) or []:
                    p = row.get("player") or {}
                    if p.get("id") is None:
                        continue
                    entries.append(
                        LineupEntry(
                            player=_player(p),
                            is_starter=starter,
                            shirt_number=as_int(p.get("number")),
                            position=p.get("pos"),
                            grid=p.get("grid"),
                        )
                    )
            coach = item.get("coach") or {}
            result.append(
                LineupData(
                    team=_team(item["team"]),
                    formation=item.get("formation"),
                    coach_name=coach.get("name"),
                    players=tuple(entries),
                )
            )
        return result

    async def absences(self, fixture_id: str) -> list[AbsenceData]:
        items = await self._get("/injuries", {"fixture": fixture_id})
        result: list[AbsenceData] = []
        for item in items:
            p = item.get("player") or {}
            if p.get("id") is None:
                continue
            kind = str(p.get("type") or "")
            reason = p.get("reason")
            category: Literal["injury", "suspension", "other"]
            if _SUSPENSION.search(str(reason or "")):
                category = "suspension"
            elif kind:
                category = "injury"
            else:
                category = "other"
            result.append(
                AbsenceData(
                    team=_team(item["team"]),
                    player=PlayerData(str(p["id"]), str(p.get("name") or "")),
                    status="questionable" if kind.lower() == "questionable" else "missing",
                    category=category,
                    reason=reason,
                )
            )
        return result
