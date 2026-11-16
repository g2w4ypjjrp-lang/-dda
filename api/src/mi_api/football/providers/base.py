"""Sağlayıcıdan bağımsız futbol verisi biçimi ve sağlayıcı arayüzü (Provider Adapter).

Her uyarlayıcı sağlayıcının yanıtını bu modüldeki veri sınıflarına çevirir; senkronizasyon
servisi ve veritabanı yalnızca bu biçimi tanır. Yeni bir sağlayıcı eklemek = yeni bir uyarlayıcı.

Kurallar:
* Sağlayıcıda olmayan alan ``None`` olur; tahmin veya varsayılan değer üretilmez.
* Zamanlar UTC'ye çevrilir (saat dilimi bilgisi olmayan zaman kabul edilmez).
* Sağlayıcının desteklemediği veri türü istenirse ``CapabilityNotSupported`` fırlatılır.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx

log = logging.getLogger(__name__)

FixtureStatus = Literal[
    "tbd", "scheduled", "live", "halftime", "finished", "postponed", "suspended", "cancelled",
    "abandoned", "awarded",
]  # fmt: skip
Capability = Literal["fixtures", "live", "standings", "team_stats", "xg", "lineups", "absences"]


class ProviderError(Exception):
    """Sağlayıcı hatası (kimlik, biçim, sunucu)."""


class QuotaExceeded(ProviderError):
    """Sağlayıcı kotası veya yerel kota bütçesi doldu."""


class CapabilityNotSupported(ProviderError):
    """Bu sağlayıcı (veya mevcut paket) bu veri türünü sunmuyor."""


@dataclass(frozen=True)
class CountryData:
    name: str
    code: str | None = None
    flag_url: str | None = None


@dataclass(frozen=True)
class CompetitionData:
    external_id: str
    name: str
    type: Literal["league", "cup", "other"] = "league"
    country: CountryData | None = None
    logo_url: str | None = None


@dataclass(frozen=True)
class SeasonData:
    year: int
    label: str
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False


@dataclass(frozen=True)
class VenueData:
    external_id: str
    name: str
    city: str | None = None
    capacity: int | None = None


@dataclass(frozen=True)
class TeamData:
    external_id: str
    name: str
    short_name: str | None = None
    code: str | None = None
    logo_url: str | None = None
    country: CountryData | None = None


@dataclass(frozen=True)
class PlayerData:
    external_id: str
    name: str
    position: str | None = None


@dataclass(frozen=True)
class Score:
    home: int | None = None
    away: int | None = None


@dataclass(frozen=True)
class FixtureData:
    external_id: str
    competition: CompetitionData
    season: SeasonData
    kickoff_at: datetime
    status: FixtureStatus
    status_detail: str | None
    home: TeamData
    away: TeamData
    round: str | None = None
    minute: int | None = None
    venue: VenueData | None = None
    referee: str | None = None
    goals: Score = field(default_factory=Score)  # uzatma dahil, penaltılar hariç
    halftime: Score = field(default_factory=Score)
    fulltime: Score = field(default_factory=Score)  # normal süre
    extratime: Score = field(default_factory=Score)  # yalnızca uzatma devresi
    penalties: Score = field(default_factory=Score)
    source_updated_at: datetime | None = None


@dataclass(frozen=True)
class TeamStatsData:
    team: TeamData
    shots_total: int | None = None
    shots_on_target: int | None = None
    possession_pct: Decimal | None = None
    corners: int | None = None
    fouls: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    offsides: int | None = None
    passes_total: int | None = None
    passes_accurate: int | None = None
    goalkeeper_saves: int | None = None
    xg: Decimal | None = None


@dataclass(frozen=True)
class StandingData:
    team: TeamData
    rank: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int
    group: str = ""
    form: str | None = None


@dataclass(frozen=True)
class LineupEntry:
    player: PlayerData
    is_starter: bool
    shirt_number: int | None = None
    position: str | None = None
    grid: str | None = None


@dataclass(frozen=True)
class LineupData:
    team: TeamData
    formation: str | None
    coach_name: str | None
    players: tuple[LineupEntry, ...]


@dataclass(frozen=True)
class AbsenceData:
    team: TeamData
    player: PlayerData
    status: Literal["missing", "questionable"]
    category: Literal["injury", "suspension", "other"]
    reason: str | None = None


@dataclass(frozen=True)
class QuotaInfo:
    daily_limit: int | None = None
    daily_remaining: int | None = None
    minute_limit: int | None = None
    minute_remaining: int | None = None


class FootballProvider(Protocol):
    name: str
    capabilities: frozenset[Capability]
    requests_made: int

    async def fixtures_by_date(self, day: date) -> list[FixtureData]: ...

    async def live_fixtures(self) -> list[FixtureData]: ...

    async def fixture(self, external_id: str) -> FixtureData | None: ...

    async def season_fixtures(self, competition_id: str, season: int) -> list[FixtureData]: ...

    async def standings(self, competition_id: str, season: int) -> list[StandingData]: ...

    async def team_stats(self, fixture_id: str) -> list[TeamStatsData]: ...

    async def lineups(self, fixture_id: str) -> list[LineupData]: ...

    async def absences(self, fixture_id: str) -> list[AbsenceData]: ...

    async def aclose(self) -> None: ...


# --- Ortak yardımcılar ---------------------------------------------------------------------------

BeforeRequest = Callable[[], Any]  # awaitable döner; kota yoksa QuotaExceeded fırlatır
QuotaObserver = Callable[[QuotaInfo], Any]


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ProviderError(f"Saat dilimi olmayan zaman: {value}")
    return parsed.astimezone(UTC)


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%")
        if not value:
            return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip().rstrip("%"))
    except ArithmeticError:
        return None


def header_int(headers: httpx.Headers, name: str) -> int | None:
    return as_int(headers.get(name))


class HttpProvider:
    """Ortak HTTP davranışı: zaman aşımı, sınırlı yeniden deneme, kota kancaları, istek sayacı."""

    name = "base"
    max_retries = 2

    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
        before_request: BeforeRequest | None = None,
        on_quota: QuotaObserver | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self.client = httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout_s, transport=transport
        )
        self.before_request = before_request
        self.on_quota = on_quota
        self.requests_made = 0

    async def aclose(self) -> None:
        await self.client.aclose()

    def quota_from(self, headers: httpx.Headers) -> QuotaInfo | None:
        return None

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(self.max_retries + 1):
            if self.before_request is not None:
                await self.before_request()
            self.requests_made += 1
            try:
                response = await self.client.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise ProviderError(
                        f"{self.name}: bağlantı hatası ({type(exc).__name__})"
                    ) from exc
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            quota = self.quota_from(response.headers)
            if quota is not None and self.on_quota is not None:
                await self.on_quota(quota)
            if response.status_code == 429:
                raise QuotaExceeded(f"{self.name}: sağlayıcı istek sınırı (429)")
            if response.status_code in (401, 403):
                raise ProviderError(
                    f"{self.name}: kimlik doğrulama reddedildi ({response.status_code})"
                )
            if response.status_code >= 500:
                if attempt == self.max_retries:
                    raise ProviderError(f"{self.name}: sunucu hatası ({response.status_code})")
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                raise ProviderError(f"{self.name}: istek reddedildi ({response.status_code})")
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(f"{self.name}: geçersiz JSON yanıtı") from exc
        raise ProviderError(f"{self.name}: istek tamamlanamadı")  # pragma: no cover
