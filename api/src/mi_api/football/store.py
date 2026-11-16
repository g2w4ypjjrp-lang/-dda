"""Normalize edilmiş sağlayıcı verisini veritabanına yazar (idempotent upsert).

* Kimlik eşleme ``(provider, external_id)`` ile yapılır.
* Açıklayıcı alanlarda gelen ``None`` mevcut değeri silmez (``COALESCE``).
* Maç kaydı yalnızca gelen veri, kayıttakinden **daha yeni çekilmişse** güncellenir; gecikmeli
  gelen eski bir yanıt güncel skoru ezemez.
* Maç bazlı listeler (istatistik, kadro, eksikler) ve puan durumu her çekimde bütünüyle yenilenir:
  sağlayıcı bir oyuncuyu listeden çıkardıysa bizde de kalkar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.football.models import (
    Absence,
    Competition,
    Country,
    Fixture,
    FixtureTeamStats,
    Lineup,
    LineupPlayer,
    Player,
    Season,
    Standing,
    Team,
    Venue,
)
from mi_api.football.providers.base import (
    AbsenceData,
    CompetitionData,
    CountryData,
    FixtureData,
    LineupData,
    PlayerData,
    SeasonData,
    StandingData,
    TeamData,
    TeamStatsData,
    VenueData,
)


def _keep(column: Any, excluded: Any) -> Any:
    """Yeni değer NULL ise eskisini koru."""
    return func.coalesce(excluded, column)


class FootballStore:
    def __init__(self, db: AsyncSession, provider: str, now: datetime) -> None:
        self.db = db
        self.provider = provider
        self.now = now
        self._teams: dict[str, int] = {}
        self._players: dict[str, int] = {}

    async def country(self, data: CountryData | None) -> int | None:
        if data is None or not data.name:
            return None
        stmt: Any = insert(Country).values(name=data.name, code=data.code, flag_url=data.flag_url)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Country.name],
            set_={
                "code": _keep(Country.code, stmt.excluded.code),
                "flag_url": _keep(Country.flag_url, stmt.excluded.flag_url),
            },
        ).returning(Country.id)
        return int((await self.db.execute(stmt)).scalar_one())

    async def competition(self, data: CompetitionData) -> int:
        country_id = await self.country(data.country)
        stmt: Any = insert(Competition).values(
            provider=self.provider,
            external_id=data.external_id,
            name=data.name,
            type=data.type,
            country_id=country_id,
            logo_url=data.logo_url,
            fetched_at=self.now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Competition.provider, Competition.external_id],
            set_={
                "name": stmt.excluded.name,
                "type": stmt.excluded.type,
                "country_id": _keep(Competition.country_id, stmt.excluded.country_id),
                "logo_url": _keep(Competition.logo_url, stmt.excluded.logo_url),
                "fetched_at": stmt.excluded.fetched_at,
            },
        ).returning(Competition.id)
        return int((await self.db.execute(stmt)).scalar_one())

    async def season(self, competition_id: int, data: SeasonData) -> int:
        stmt: Any = insert(Season).values(
            competition_id=competition_id,
            year=data.year,
            label=data.label,
            start_date=data.start_date,
            end_date=data.end_date,
            is_current=data.is_current,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Season.competition_id, Season.year],
            set_={
                "start_date": _keep(Season.start_date, stmt.excluded.start_date),
                "end_date": _keep(Season.end_date, stmt.excluded.end_date),
            },
        ).returning(Season.id)
        return int((await self.db.execute(stmt)).scalar_one())

    async def venue(self, data: VenueData | None) -> int | None:
        if data is None:
            return None
        stmt: Any = insert(Venue).values(
            provider=self.provider,
            external_id=data.external_id,
            name=data.name,
            city=data.city,
            capacity=data.capacity,
            fetched_at=self.now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Venue.provider, Venue.external_id],
            set_={
                "name": stmt.excluded.name,
                "city": _keep(Venue.city, stmt.excluded.city),
                "capacity": _keep(Venue.capacity, stmt.excluded.capacity),
                "fetched_at": stmt.excluded.fetched_at,
            },
        ).returning(Venue.id)
        return int((await self.db.execute(stmt)).scalar_one())

    async def team(self, data: TeamData) -> int:
        cached = self._teams.get(data.external_id)
        if cached is not None:
            return cached
        country_id = await self.country(data.country)
        stmt: Any = insert(Team).values(
            provider=self.provider,
            external_id=data.external_id,
            name=data.name,
            short_name=data.short_name,
            code=data.code,
            country_id=country_id,
            logo_url=data.logo_url,
            fetched_at=self.now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Team.provider, Team.external_id],
            set_={
                "name": stmt.excluded.name,
                "short_name": _keep(Team.short_name, stmt.excluded.short_name),
                "code": _keep(Team.code, stmt.excluded.code),
                "country_id": _keep(Team.country_id, stmt.excluded.country_id),
                "logo_url": _keep(Team.logo_url, stmt.excluded.logo_url),
                "fetched_at": stmt.excluded.fetched_at,
            },
        ).returning(Team.id)
        team_id = int((await self.db.execute(stmt)).scalar_one())
        self._teams[data.external_id] = team_id
        return team_id

    async def player(self, data: PlayerData) -> int:
        cached = self._players.get(data.external_id)
        if cached is not None:
            return cached
        stmt: Any = insert(Player).values(
            provider=self.provider,
            external_id=data.external_id,
            name=data.name or data.external_id,
            position=data.position,
            fetched_at=self.now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Player.provider, Player.external_id],
            set_={
                "name": func.coalesce(func.nullif(stmt.excluded.name, ""), Player.name),
                "position": _keep(Player.position, stmt.excluded.position),
                "fetched_at": stmt.excluded.fetched_at,
            },
        ).returning(Player.id)
        player_id = int((await self.db.execute(stmt)).scalar_one())
        self._players[data.external_id] = player_id
        return player_id

    async def fixture(self, data: FixtureData) -> int:
        competition_id = await self.competition(data.competition)
        season_id = await self.season(competition_id, data.season)
        home_id = await self.team(data.home)
        away_id = await self.team(data.away)
        venue_id = await self.venue(data.venue)
        values: dict[str, Any] = {
            "provider": self.provider,
            "external_id": data.external_id,
            "season_id": season_id,
            "round": data.round,
            "kickoff_at": data.kickoff_at,
            "status": data.status,
            "status_detail": data.status_detail,
            "minute": data.minute,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "venue_id": venue_id,
            "referee": data.referee,
            "home_goals": data.goals.home,
            "away_goals": data.goals.away,
            "ht_home": data.halftime.home,
            "ht_away": data.halftime.away,
            "ft_home": data.fulltime.home,
            "ft_away": data.fulltime.away,
            "et_home": data.extratime.home,
            "et_away": data.extratime.away,
            "pen_home": data.penalties.home,
            "pen_away": data.penalties.away,
            "fetched_at": self.now,
            "source_updated_at": data.source_updated_at,
        }
        stmt: Any = insert(Fixture).values(**values)
        updatable = {k: stmt.excluded[k] for k in values if k not in ("provider", "external_id")}
        updatable["venue_id"] = _keep(Fixture.venue_id, stmt.excluded.venue_id)
        updatable["referee"] = _keep(Fixture.referee, stmt.excluded.referee)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Fixture.provider, Fixture.external_id],
            set_=updatable,
            where=Fixture.fetched_at <= stmt.excluded.fetched_at,
        ).returning(Fixture.id)
        fixture_id = (await self.db.execute(stmt)).scalar_one_or_none()
        if fixture_id is None:  # daha yeni veri zaten kayıtlı; güncellenmedi
            fixture_id = (
                await self.db.execute(
                    select(Fixture.id).where(
                        Fixture.provider == self.provider, Fixture.external_id == data.external_id
                    )
                )
            ).scalar_one()
        return int(fixture_id)

    async def team_stats(self, fixture_id: int, rows: list[TeamStatsData]) -> int:
        await self.db.execute(
            delete(FixtureTeamStats).where(FixtureTeamStats.fixture_id == fixture_id)
        )
        for row in rows:
            team_id = await self.team(row.team)
            values = {k: v for k, v in vars(row).items() if k != "team"}
            self.db.add(
                FixtureTeamStats(
                    fixture_id=fixture_id,
                    team_id=team_id,
                    provider=self.provider,
                    fetched_at=self.now,
                    **values,
                )
            )
        await self.db.flush()
        return len(rows)

    async def standings(self, season_id: int, rows: list[StandingData]) -> int:
        await self.db.execute(delete(Standing).where(Standing.season_id == season_id))
        for row in rows:
            self.db.add(
                Standing(
                    season_id=season_id,
                    group_name=row.group,
                    team_id=await self.team(row.team),
                    rank=row.rank,
                    played=row.played,
                    won=row.won,
                    drawn=row.drawn,
                    lost=row.lost,
                    goals_for=row.goals_for,
                    goals_against=row.goals_against,
                    points=row.points,
                    form=row.form,
                    provider=self.provider,
                    fetched_at=self.now,
                )
            )
        await self.db.flush()
        return len(rows)

    async def lineups(self, fixture_id: int, rows: list[LineupData]) -> int:
        await self.db.execute(delete(Lineup).where(Lineup.fixture_id == fixture_id))
        count = 0
        for row in rows:
            team_id = await self.team(row.team)
            self.db.add(
                Lineup(
                    fixture_id=fixture_id,
                    team_id=team_id,
                    formation=row.formation,
                    coach_name=row.coach_name,
                    provider=self.provider,
                    fetched_at=self.now,
                )
            )
            await self.db.flush()
            seen: set[int] = set()
            for entry in row.players:
                player_id = await self.player(entry.player)
                if player_id in seen:
                    continue
                seen.add(player_id)
                self.db.add(
                    LineupPlayer(
                        fixture_id=fixture_id,
                        team_id=team_id,
                        player_id=player_id,
                        is_starter=entry.is_starter,
                        shirt_number=entry.shirt_number,
                        position=entry.position,
                        grid=entry.grid,
                    )
                )
                count += 1
        await self.db.flush()
        return count

    async def absences(self, fixture_id: int, rows: list[AbsenceData]) -> int:
        await self.db.execute(delete(Absence).where(Absence.fixture_id == fixture_id))
        seen: set[int] = set()
        for row in rows:
            player_id = await self.player(row.player)
            if player_id in seen:
                continue
            seen.add(player_id)
            self.db.add(
                Absence(
                    fixture_id=fixture_id,
                    team_id=await self.team(row.team),
                    player_id=player_id,
                    status=row.status,
                    category=row.category,
                    reason=row.reason,
                    provider=self.provider,
                    fetched_at=self.now,
                )
            )
        await self.db.flush()
        return len(seen)
