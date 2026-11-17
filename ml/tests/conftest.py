"""Veritabanı testleri: gerçek PostgreSQL (``MI_TEST_DATABASE_URL``), API geçişleriyle kurulan şema."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from mi_api.migrate import sync_url, upgrade
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from mi_ml.features import Match

BASE_URL = os.environ.get("MI_TEST_DATABASE_URL")
TEMPLATE_DB = f"mi_ml_tpl_{os.getpid()}"


def _with_db(url: str, name: str) -> str:
    return urlunparse(urlparse(url)._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
def template_dsn() -> Iterator[str]:
    if not BASE_URL:
        pytest.skip("MI_TEST_DATABASE_URL tanımlı değil")
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}"')
        admin.execute(f'CREATE DATABASE "{TEMPLATE_DB}"')
    dsn = _with_db(BASE_URL, TEMPLATE_DB)
    upgrade(dsn)
    yield dsn
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}" WITH (FORCE)')


@pytest.fixture
def dsn(template_dsn: str) -> Iterator[str]:
    assert BASE_URL
    name = f"mi_ml_t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE_DB}"')
    yield _with_db(BASE_URL, name)
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def sql(dsn: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        yield conn


@pytest.fixture
def session(dsn: str) -> Iterator[Session]:
    engine = create_engine(sync_url(dsn))
    with Session(engine) as s:
        yield s
    engine.dispose()


def load_league(
    sql: psycopg.Connection[Any], matches: list[Match], *, fetched_at: datetime
) -> dict[str, int]:
    """Sentetik maçları Faz 2 tablolarına yazar (yalnızca test). Takım adı → takım kimliği döner."""
    comp = sql.execute(
        "INSERT INTO football_competitions (provider, external_id, name, fetched_at, is_active)"
        " VALUES ('test', 'L1', 'Sentetik Lig', %s, true) RETURNING id",
        (fetched_at,),
    ).fetchone()[0]
    teams: dict[str, int] = {}
    for name in sorted({m.home for m in matches} | {m.away for m in matches}):
        teams[name] = sql.execute(
            "INSERT INTO football_teams (provider, external_id, name, fetched_at) VALUES ('test', %s, %s, %s) RETURNING id",
            (name, f"Sentetik {name}", fetched_at),
        ).fetchone()[0]
    seasons: dict[int, int] = {}
    for m in matches:
        year = m.kickoff_at.year if m.kickoff_at.month >= 7 else m.kickoff_at.year - 1
        if year not in seasons:
            seasons[year] = sql.execute(
                "INSERT INTO football_seasons (competition_id, year, label) VALUES (%s, %s, %s) RETURNING id",
                (comp, year, f"{year}/{(year + 1) % 100:02d}"),
            ).fetchone()[0]
        played = m.home_goals >= 0
        sql.execute(
            "INSERT INTO football_fixtures (provider, external_id, season_id, kickoff_at, status, status_detail,"
            " home_team_id, away_team_id, home_goals, away_goals, ft_home, ft_away, ht_home, ht_away, fetched_at)"
            " VALUES ('test', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(m.fixture_id),
                seasons[year],
                m.kickoff_at,
                "finished" if played else "scheduled",
                "FT" if played else "NS",
                teams[m.home],
                teams[m.away],
                m.home_goals if played else None,
                m.away_goals if played else None,
                m.home_goals if played else None,
                m.away_goals if played else None,
                m.ht_home if played else None,
                m.ht_away if played else None,
                fetched_at,
            ),
        )
    return {"competition_id": comp, **teams}


def future(after: datetime, home: str, away: str, days: int, fixture_id: int) -> Match:
    return Match(after + timedelta(days=days), home, away, -1, -1, fixture_id=fixture_id)


NOW = datetime(2027, 6, 1, 12, 0, tzinfo=UTC)
