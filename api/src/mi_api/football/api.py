"""Futbol verisi API'si.

Herkese açık okuma (``/v1/football``) ve yönetim (``/admin/v1/football``).

* Zamanlar UTC olarak döner (``kickoff_at``); ayrıca Türkiye saati (``kickoff_local``) verilir.
  ``date`` parametresi **Türkiye takvim günüdür** (16 Kasım 22:30 UTC maçı 17 Kasım'dadır).
* Her maçta kaynak ve tazelik bilgisi bulunur; bayat veri ``freshness.stale=true`` ile işaretlenir.
* Sağlayıcı yapılandırılmamışsa yanıtlar boş liste ve ``data_status="no_provider"`` döner; veri
  uydurulmaz.
* Abonelik planına göre kısıtlama Faz 6'da eklenecek.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mi_api import audit
from mi_api.context import DbDep, MetaDep, Principal, ServicesDep, require_permission
from mi_api.errors import ApiError
from mi_api.football.models import (
    Absence,
    Competition,
    Country,
    Fixture,
    FixtureTeamStats,
    Lineup,
    LineupPlayer,
    Player,
    ProviderStatus,
    Season,
    Standing,
    SyncRun,
    Team,
    Venue,
)
from mi_api.football.providers.api_football import ApiFootballProvider
from mi_api.football.providers.base import Capability
from mi_api.football.providers.football_data import FootballDataProvider
from mi_api.football.quality import completeness, freshness
from mi_api.football.runtime import PROVIDER_LABELS, FootballRuntime
from mi_api.football.sync import Job

TR = ZoneInfo("Europe/Istanbul")
FixtureStatusFilter = Literal[
    "tbd", "scheduled", "live", "halftime", "finished", "postponed", "suspended", "cancelled",
    "abandoned", "awarded",
]  # fmt: skip


def get_runtime(request: Request) -> FootballRuntime:
    runtime: FootballRuntime = request.app.state.football
    return runtime


RuntimeDep = Annotated[FootballRuntime, Depends(get_runtime)]


def tr_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=TR)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _team_view(team: Team) -> dict[str, Any]:
    return {
        "id": team.id,
        "name": team.name,
        "short_name": team.short_name,
        "logo_url": team.logo_url,
    }


def _score(h: int | None, a: int | None) -> dict[str, int] | None:
    return {"home": h, "away": a} if h is not None and a is not None else None


Home = aliased(Team)
Away = aliased(Team)


def _fixture_query() -> Any:
    return (
        select(Fixture, Home, Away, Competition, Season)
        .join(Home, Home.id == Fixture.home_team_id)
        .join(Away, Away.id == Fixture.away_team_id)
        .join(Season, Season.id == Fixture.season_id)
        .join(Competition, Competition.id == Season.competition_id)
    )


def fixture_view(
    fx: Fixture, home: Team, away: Team, comp: Competition, season: Season, now: datetime
) -> dict[str, Any]:
    return {
        "id": fx.id,
        "kickoff_at": fx.kickoff_at.isoformat(),
        "kickoff_local": fx.kickoff_at.astimezone(TR).isoformat(),
        "status": fx.status,
        "status_detail": fx.status_detail,
        "minute": fx.minute,
        "round": fx.round,
        "competition": {"id": comp.id, "name": comp.name, "logo_url": comp.logo_url},
        "season": {"id": season.id, "year": season.year, "label": season.label},
        "home": _team_view(home),
        "away": _team_view(away),
        "score": {
            "current": _score(fx.home_goals, fx.away_goals),
            "halftime": _score(fx.ht_home, fx.ht_away),
            "fulltime": _score(fx.ft_home, fx.ft_away),
            "extratime": _score(fx.et_home, fx.et_away),
            "penalties": _score(fx.pen_home, fx.pen_away),
        },
        "source": {
            "provider": fx.provider,
            "provider_label": PROVIDER_LABELS.get(fx.provider, fx.provider),
            "source_updated_at": _iso(fx.source_updated_at),
        },
        "freshness": freshness(fx.status, fx.kickoff_at, fx.fetched_at, now),
    }


async def _status_payload(db: AsyncSession, runtime: FootballRuntime) -> dict[str, Any]:
    status = await db.get(ProviderStatus, runtime.provider_name) if runtime.configured else None
    last_ok = (
        await db.execute(
            select(func.max(SyncRun.finished_at)).where(
                SyncRun.provider == runtime.provider_name, SyncRun.status == "succeeded"
            )
        )
    ).scalar_one_or_none()
    return {
        "data_status": "ok" if runtime.configured else "no_provider",
        "provider": runtime.provider_name,
        "provider_label": PROVIDER_LABELS.get(runtime.provider_name, runtime.provider_name),
        "last_successful_sync_at": _iso(last_ok),
        "last_error_at": _iso(status.last_error_at) if status else None,
    }


class SyncBody(BaseModel):
    job: Job
    day: date | None = Field(default=None, alias="date")
    fixture_id: int | None = Field(default=None, ge=1)
    competition_id: int | None = Field(default=None, ge=1)
    season: int | None = Field(default=None, ge=1850, le=2200)


class CompetitionPatch(BaseModel):
    is_active: bool


def create_football_router() -> APIRouter:
    router = APIRouter(tags=["football"])

    # --- Herkese açık ---------------------------------------------------------------------------

    @router.get("/v1/football/status")
    async def status(db: DbDep, runtime: RuntimeDep) -> dict[str, Any]:
        return await _status_payload(db, runtime)

    @router.get("/v1/football/fixtures")
    async def fixtures(
        db: DbDep,
        services: ServicesDep,
        runtime: RuntimeDep,
        day: Annotated[date | None, Query(alias="date")] = None,
        competition_id: Annotated[int | None, Query(ge=1)] = None,
        status: FixtureStatusFilter | None = None,
    ) -> dict[str, Any]:
        now = services.clock()
        local_day = day or now.astimezone(TR).date()
        start, end = tr_day_bounds(local_day)
        stmt = _fixture_query().where(Fixture.kickoff_at >= start, Fixture.kickoff_at < end)
        if competition_id:
            stmt = stmt.where(Competition.id == competition_id)
        if status:
            stmt = stmt.where(Fixture.status == status)
        rows = (
            await db.execute(
                stmt.order_by(Fixture.kickoff_at, Competition.name, Fixture.id).limit(1000)
            )
        ).all()
        items = [
            fixture_view(fx, home, away, comp, season_row, now)
            for fx, home, away, comp, season_row in rows
        ]
        return {
            "date": local_day.isoformat(),
            "timezone": "Europe/Istanbul",
            "items": items,
            **await _status_payload(db, runtime),
        }

    @router.get("/v1/football/fixtures/{fixture_id}")
    async def fixture_detail(
        fixture_id: int, db: DbDep, services: ServicesDep, runtime: RuntimeDep
    ) -> dict[str, Any]:
        now = services.clock()
        row = (await db.execute(_fixture_query().where(Fixture.id == fixture_id))).one_or_none()
        if row is None:
            raise ApiError(404, "not_found", "Maç bulunamadı")
        fx, home, away, comp, season = row
        view = fixture_view(fx, home, away, comp, season, now)

        venue = await db.get(Venue, fx.venue_id) if fx.venue_id else None
        view["venue"] = {"name": venue.name, "city": venue.city} if venue else None
        view["referee"] = fx.referee

        stats = (
            (await db.execute(select(FixtureTeamStats).where(FixtureTeamStats.fixture_id == fx.id)))
            .scalars()
            .all()
        )
        side = {fx.home_team_id: "home", fx.away_team_id: "away"}
        stat_fields = (
            "shots_total", "shots_on_target", "possession_pct", "corners", "fouls", "yellow_cards",
            "red_cards", "offsides", "passes_total", "passes_accurate", "goalkeeper_saves", "xg",
        )  # fmt: skip
        view["team_stats"] = {
            side.get(s.team_id, str(s.team_id)): {
                **{
                    f: (float(v) if v is not None and f in ("possession_pct", "xg") else v)
                    for f in stat_fields
                    for v in [getattr(s, f)]
                },
                "fetched_at": s.fetched_at.isoformat(),
            }
            for s in stats
        }

        lineups = (
            (await db.execute(select(Lineup).where(Lineup.fixture_id == fx.id))).scalars().all()
        )
        players = (
            await db.execute(
                select(LineupPlayer, Player)
                .join(Player, Player.id == LineupPlayer.player_id)
                .where(LineupPlayer.fixture_id == fx.id)
                .order_by(LineupPlayer.is_starter.desc(), LineupPlayer.shirt_number)
            )
        ).all()
        view["lineups"] = {
            side.get(lu.team_id, str(lu.team_id)): {
                "formation": lu.formation,
                "coach": lu.coach_name,
                "fetched_at": lu.fetched_at.isoformat(),
                "players": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "number": lp.shirt_number,
                        "position": lp.position,
                        "grid": lp.grid,
                        "starter": lp.is_starter,
                    }
                    for lp, p in players
                    if lp.team_id == lu.team_id
                ],
            }
            for lu in lineups
        }
        absences = (
            await db.execute(
                select(Absence, Player)
                .join(Player, Player.id == Absence.player_id)
                .where(Absence.fixture_id == fx.id)
            )
        ).all()
        view["absences"] = [
            {
                "side": side.get(a.team_id),
                "player": p.name,
                "status": a.status,
                "category": a.category,
                "reason": a.reason,
                "fetched_at": a.fetched_at.isoformat(),
            }
            for a, p in absences
        ]
        caps = _capabilities(runtime) if runtime.configured else frozenset()
        view["completeness"] = completeness(
            status=fx.status,
            kickoff_at=fx.kickoff_at,
            fetched_at=fx.fetched_at,
            now=now,
            capabilities=caps,
            has_stats=bool(stats),
            has_xg=any(s.xg is not None for s in stats),
            has_lineups=bool(lineups),
            has_halftime=fx.ht_home is not None,
        )
        return view

    @router.get("/v1/football/competitions")
    async def competitions(
        db: DbDep, active_only: bool = True, q: Annotated[str | None, Query(max_length=80)] = None
    ) -> dict[str, Any]:
        stmt = select(Competition, Country).outerjoin(Country, Country.id == Competition.country_id)
        if active_only:
            stmt = stmt.where(Competition.is_active)
        if q:
            stmt = stmt.where(
                Competition.name.ilike("%" + q.replace("%", "\\%").replace("_", "\\_") + "%")
            )
        rows = (await db.execute(stmt.order_by(Country.name, Competition.name).limit(500))).all()
        return {
            "items": [
                {
                    "id": c.id,
                    "name": c.name,
                    "type": c.type,
                    "logo_url": c.logo_url,
                    "country": country.name if country else None,
                    "is_active": c.is_active,
                }
                for c, country in rows
            ]
        }

    @router.get("/v1/football/competitions/{competition_id}/standings")
    async def standings(
        competition_id: int,
        db: DbDep,
        season: Annotated[int | None, Query(ge=1850, le=2200)] = None,
    ) -> dict[str, Any]:
        comp = await db.get(Competition, competition_id)
        if comp is None:
            raise ApiError(404, "not_found", "Lig bulunamadı")
        season_stmt = select(Season).where(Season.competition_id == comp.id)
        season_stmt = (
            season_stmt.where(Season.year == season)
            if season
            else season_stmt.where(Season.id.in_(select(Standing.season_id).distinct())).order_by(
                Season.year.desc()
            )
        )
        season_row = (await db.execute(season_stmt.limit(1))).scalar_one_or_none()
        if season_row is None:
            return {"competition": {"id": comp.id, "name": comp.name}, "season": None, "groups": []}
        rows = (
            await db.execute(
                select(Standing, Team)
                .join(Team, Team.id == Standing.team_id)
                .where(Standing.season_id == season_row.id)
                .order_by(Standing.group_name, Standing.rank)
            )
        ).all()
        groups: dict[str, list[dict[str, Any]]] = {}
        fetched: datetime | None = None
        for st, team in rows:
            fetched = max(fetched, st.fetched_at) if fetched else st.fetched_at
            groups.setdefault(st.group_name, []).append(
                {
                    "rank": st.rank,
                    "team": _team_view(team),
                    "played": st.played,
                    "won": st.won,
                    "drawn": st.drawn,
                    "lost": st.lost,
                    "goals_for": st.goals_for,
                    "goals_against": st.goals_against,
                    "goal_diff": st.goals_for - st.goals_against,
                    "points": st.points,
                    "form": st.form,
                }
            )
        return {
            "competition": {"id": comp.id, "name": comp.name},
            "season": {"year": season_row.year, "label": season_row.label},
            "fetched_at": _iso(fetched),
            "groups": [{"name": name, "table": table} for name, table in groups.items()],
        }

    # --- Yönetim ----------------------------------------------------------------------------

    @router.get("/admin/v1/football/status")
    async def admin_status(
        db: DbDep,
        services: ServicesDep,
        runtime: RuntimeDep,
        _: Principal = Depends(require_permission("football.read")),
    ) -> dict[str, Any]:
        provider_row = await db.get(ProviderStatus, runtime.provider_name)
        counts = dict(
            (await db.execute(select(Fixture.status, func.count()).group_by(Fixture.status))).all()
        )
        return {
            **await _status_payload(db, runtime),
            "capabilities": sorted(_capabilities(runtime)) if runtime.configured else [],
            "budget": {
                "daily": services.settings.football_daily_budget,
                "minute": services.settings.football_minute_budget,
                "reserve_pct": services.settings.football_reserve_pct,
                "used_today": await runtime.budget.used_today() if runtime.budget else 0,
            },
            "provider_reported": {
                "daily_limit": provider_row.daily_limit,
                "daily_remaining": provider_row.daily_remaining,
                "minute_limit": provider_row.minute_limit,
                "minute_remaining": provider_row.minute_remaining,
                "observed_at": _iso(provider_row.observed_at),
                "last_error": provider_row.last_error,
            }
            if provider_row
            else None,
            "fixture_counts": counts,
            "active_competitions": (
                await db.execute(
                    select(func.count()).select_from(Competition).where(Competition.is_active)
                )
            ).scalar_one(),
        }

    @router.get("/admin/v1/football/sync-runs")
    async def sync_runs(
        db: DbDep,
        _: Principal = Depends(require_permission("football.read")),
        job: Job | None = None,
        status: Literal["running", "succeeded", "failed", "skipped"] | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        stmt = select(SyncRun)
        if job:
            stmt = stmt.where(SyncRun.job == job)
        if status:
            stmt = stmt.where(SyncRun.status == status)
        rows = (await db.execute(stmt.order_by(SyncRun.id.desc()).limit(limit))).scalars().all()
        return {
            "items": [
                {
                    "id": r.id,
                    "provider": r.provider,
                    "job": r.job,
                    "params": r.params,
                    "trigger": r.trigger,
                    "status": r.status,
                    "started_at": r.started_at.isoformat(),
                    "finished_at": _iso(r.finished_at),
                    "requests": r.requests,
                    "items": r.items,
                    "message": r.message,
                }
                for r in rows
            ]
        }

    @router.post("/admin/v1/football/sync")
    async def trigger_sync(
        body: SyncBody,
        db: DbDep,
        services: ServicesDep,
        runtime: RuntimeDep,
        meta: MetaDep,
        admin: Principal = Depends(require_permission("football.manage")),
    ) -> dict[str, Any]:
        params = {
            k: (v.isoformat() if isinstance(v, date) else v)
            for k, v in body.model_dump(exclude={"job"}, by_alias=True).items()
            if v is not None
        }
        service, provider = runtime.service(services.db)
        try:
            result = await service.run(body.job, params, trigger="admin")
        finally:
            if provider is not None:
                await provider.aclose()
        await audit.record(
            db, "admin.football_sync", actor_type="admin", actor_id=admin.actor_id,
            target_type="sync_run", target_id=str(result.run_id), ip=meta.ip,
            details={"job": body.job, "params": params, "status": result.status},
        )  # fmt: skip
        return result.as_dict()

    @router.patch("/admin/v1/football/competitions/{competition_id}")
    async def patch_competition(
        competition_id: int,
        body: CompetitionPatch,
        db: DbDep,
        meta: MetaDep,
        admin: Principal = Depends(require_permission("football.manage")),
    ) -> dict[str, Any]:
        comp = await db.get(Competition, competition_id, with_for_update=True)
        if comp is None:
            raise ApiError(404, "not_found", "Lig bulunamadı")
        if comp.is_active != body.is_active:
            comp.is_active = body.is_active
            await audit.record(
                db, "admin.competition_tracking_changed", actor_type="admin",
                actor_id=admin.actor_id, target_type="competition", target_id=str(comp.id),
                ip=meta.ip, details={"is_active": body.is_active, "name": comp.name},
            )  # fmt: skip
        return {"id": comp.id, "name": comp.name, "is_active": comp.is_active}

    return router


def _capabilities(runtime: FootballRuntime) -> frozenset[Capability]:
    return {
        "api_football": ApiFootballProvider.capabilities,
        "football_data": FootballDataProvider.capabilities,
    }.get(runtime.provider_name, frozenset())
