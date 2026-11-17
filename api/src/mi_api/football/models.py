"""Faz 2 futbol verisi ORM modelleri (şema kaynağı: geçiş 0002)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mi_api.models import Base


class Country(Base):
    __tablename__ = "football_countries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    code: Mapped[str | None] = mapped_column(String(8))
    flag_url: Mapped[str | None] = mapped_column(Text)


class Competition(Base):
    __tablename__ = "football_competitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(16), default="league")
    country_id: Mapped[int | None] = mapped_column(ForeignKey("football_countries.id"))
    logo_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Season(Base):
    __tablename__ = "football_seasons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("football_competitions.id"))
    year: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)


class Venue(Base):
    __tablename__ = "football_venues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    capacity: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Team(Base):
    __tablename__ = "football_teams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    short_name: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(String(8))
    country_id: Mapped[int | None] = mapped_column(ForeignKey("football_countries.id"))
    logo_url: Mapped[str | None] = mapped_column(Text)
    founded: Mapped[int | None] = mapped_column(Integer)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("football_venues.id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Player(Base):
    __tablename__ = "football_players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    birth_date: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(Text)
    position: Mapped[str | None] = mapped_column(String(16))
    photo_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Fixture(Base):
    __tablename__ = "football_fixtures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    season_id: Mapped[int] = mapped_column(ForeignKey("football_seasons.id"))
    round: Mapped[str | None] = mapped_column(Text)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    status_detail: Mapped[str | None] = mapped_column(String(32))
    minute: Mapped[int | None] = mapped_column(SmallInteger)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("football_teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("football_teams.id"))
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("football_venues.id"))
    referee: Mapped[str | None] = mapped_column(Text)
    home_goals: Mapped[int | None] = mapped_column(SmallInteger)
    away_goals: Mapped[int | None] = mapped_column(SmallInteger)
    ht_home: Mapped[int | None] = mapped_column(SmallInteger)
    ht_away: Mapped[int | None] = mapped_column(SmallInteger)
    ft_home: Mapped[int | None] = mapped_column(SmallInteger)
    ft_away: Mapped[int | None] = mapped_column(SmallInteger)
    et_home: Mapped[int | None] = mapped_column(SmallInteger)
    et_away: Mapped[int | None] = mapped_column(SmallInteger)
    pen_home: Mapped[int | None] = mapped_column(SmallInteger)
    pen_away: Mapped[int | None] = mapped_column(SmallInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FixtureTeamStats(Base):
    __tablename__ = "football_fixture_team_stats"

    fixture_id: Mapped[int] = mapped_column(ForeignKey("football_fixtures.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("football_teams.id"), primary_key=True)
    shots_total: Mapped[int | None] = mapped_column(SmallInteger)
    shots_on_target: Mapped[int | None] = mapped_column(SmallInteger)
    possession_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    corners: Mapped[int | None] = mapped_column(SmallInteger)
    fouls: Mapped[int | None] = mapped_column(SmallInteger)
    yellow_cards: Mapped[int | None] = mapped_column(SmallInteger)
    red_cards: Mapped[int | None] = mapped_column(SmallInteger)
    offsides: Mapped[int | None] = mapped_column(SmallInteger)
    passes_total: Mapped[int | None] = mapped_column(Integer)
    passes_accurate: Mapped[int | None] = mapped_column(Integer)
    goalkeeper_saves: Mapped[int | None] = mapped_column(SmallInteger)
    xg: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    provider: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Standing(Base):
    __tablename__ = "football_standings"

    season_id: Mapped[int] = mapped_column(ForeignKey("football_seasons.id"), primary_key=True)
    group_name: Mapped[str] = mapped_column(Text, primary_key=True, default="")
    team_id: Mapped[int] = mapped_column(ForeignKey("football_teams.id"), primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger)
    played: Mapped[int] = mapped_column(SmallInteger)
    won: Mapped[int] = mapped_column(SmallInteger)
    drawn: Mapped[int] = mapped_column(SmallInteger)
    lost: Mapped[int] = mapped_column(SmallInteger)
    goals_for: Mapped[int] = mapped_column(SmallInteger)
    goals_against: Mapped[int] = mapped_column(SmallInteger)
    points: Mapped[int] = mapped_column(SmallInteger)
    form: Mapped[str | None] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Lineup(Base):
    __tablename__ = "football_lineups"

    fixture_id: Mapped[int] = mapped_column(ForeignKey("football_fixtures.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("football_teams.id"), primary_key=True)
    formation: Mapped[str | None] = mapped_column(String(16))
    coach_name: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LineupPlayer(Base):
    __tablename__ = "football_lineup_players"

    fixture_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    team_id: Mapped[int] = mapped_column(BigInteger)
    player_id: Mapped[int] = mapped_column(ForeignKey("football_players.id"), primary_key=True)
    is_starter: Mapped[bool] = mapped_column(Boolean)
    shirt_number: Mapped[int | None] = mapped_column(SmallInteger)
    position: Mapped[str | None] = mapped_column(String(8))
    grid: Mapped[str | None] = mapped_column(String(8))


class Absence(Base):
    __tablename__ = "football_absences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("football_fixtures.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("football_teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("football_players.id"))
    status: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderStatus(Base):
    __tablename__ = "football_provider_status"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    daily_limit: Mapped[int | None] = mapped_column(Integer)
    daily_remaining: Mapped[int | None] = mapped_column(Integer)
    minute_limit: Mapped[int | None] = mapped_column(Integer)
    minute_remaining: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class SyncRun(Base):
    __tablename__ = "football_sync_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    job: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requests: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
