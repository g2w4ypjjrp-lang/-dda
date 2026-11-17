"""Veritabanından model girdisi okuma (Faz 2 tabloları).

* Takım kimliği olarak iç veritabanı kimliği (metin) kullanılır.
* Model **normal süre (90') skorunu** kullanır (``ft_home/ft_away``). Normal sürede biten maçta
  sağlayıcı ``ft`` vermediyse nihai skor kullanılır; uzatma/penaltıyla biten ve ``ft`` olmayan maç
  dışlanır (90' skoru bilinmiyor, uydurulmaz).
* xG yalnızca sağlayıcı verdiyse doldurulur.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from mi_api.football.models import Fixture, FixtureTeamStats, Lineup, Season
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from mi_ml.features import Match

REGULAR_TIME = ("FT", "FINISHED")


def _xg(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


def _ht_ok(fx: Fixture, home_goals: int, away_goals: int) -> bool:
    return (
        fx.ht_home is not None
        and fx.ht_away is not None
        and fx.ht_home <= home_goals
        and fx.ht_away <= away_goals
    )


def load_played(
    session: Session, competition_ids: Sequence[int], *, before: datetime | None = None
) -> list[Match]:
    hs = aliased(FixtureTeamStats)
    aws = aliased(FixtureTeamStats)
    stmt = (
        select(Fixture, Season.competition_id, hs.xg, aws.xg)
        .join(Season, Season.id == Fixture.season_id)
        .outerjoin(hs, and_(hs.fixture_id == Fixture.id, hs.team_id == Fixture.home_team_id))
        .outerjoin(aws, and_(aws.fixture_id == Fixture.id, aws.team_id == Fixture.away_team_id))
        .where(Season.competition_id.in_(list(competition_ids)), Fixture.status == "finished")
        .order_by(Fixture.kickoff_at, Fixture.id)
    )
    if before is not None:
        stmt = stmt.where(Fixture.kickoff_at < before)
    out: list[Match] = []
    for fx, comp_id, xg_h, xg_a in session.execute(stmt):
        if fx.ft_home is not None and fx.ft_away is not None:
            home_goals, away_goals = fx.ft_home, fx.ft_away
        elif (
            fx.status_detail in REGULAR_TIME
            and fx.home_goals is not None
            and fx.away_goals is not None
        ):
            home_goals, away_goals = fx.home_goals, fx.away_goals
        else:
            continue
        out.append(
            Match(
                fx.kickoff_at,
                str(fx.home_team_id),
                str(fx.away_team_id),
                int(home_goals),
                int(away_goals),
                fixture_id=fx.id,
                competition_id=int(comp_id),
                xg_home=_xg(xg_h),
                xg_away=_xg(xg_a),
                # İY skoru yalnızca 90' skoruyla tutarlıysa kullanılır (İY ≤ MS).
                ht_home=fx.ht_home if _ht_ok(fx, home_goals, away_goals) else None,
                ht_away=fx.ht_away if _ht_ok(fx, home_goals, away_goals) else None,
            )
        )
    return out


@dataclass(frozen=True)
class Target:
    fixture: Fixture
    match: Match
    has_lineups: bool


def load_targets(
    session: Session, competition_ids: Sequence[int], *, now: datetime, horizon: timedelta
) -> list[Target]:
    stmt = (
        select(Fixture, Season.competition_id)
        .join(Season, Season.id == Fixture.season_id)
        .where(
            Season.competition_id.in_(list(competition_ids)),
            Fixture.status.in_(("scheduled", "tbd")),
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= now + horizon,
        )
        .order_by(Fixture.kickoff_at, Fixture.id)
    )
    rows = session.execute(stmt).all()
    with_lineups = set(
        session.scalars(
            select(Lineup.fixture_id).where(Lineup.fixture_id.in_([fx.id for fx, _ in rows]))
        )
    )
    return [
        Target(
            fx,
            Match(
                fx.kickoff_at,
                str(fx.home_team_id),
                str(fx.away_team_id),
                -1,
                -1,
                fixture_id=fx.id,
                competition_id=int(comp_id),
            ),
            fx.id in with_lineups,
        )
        for fx, comp_id in rows
    ]
