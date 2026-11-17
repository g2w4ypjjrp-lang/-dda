"""Futbol verisi senkronizasyon işleri.

Her iş ``football_sync_runs`` tablosunda bir kayıt bırakır (başladı → başarılı / başarısız /
atlandı, istek ve kayıt sayısı, mesaj). İş kaydı ayrı işlemde yazılır; iş başarısız olsa da kalır.

İşler ve öncelikleri (``high`` bütçenin tamamını, ``low`` rezerv hariç kısmını kullanır):

* ``fixtures_date`` (high): bir UTC gününün tüm maçları.
* ``live`` (high): canlı maçlar; veritabanında canlı/başlamak üzere maç yoksa istek atılmaz.
* ``fixture_details`` (low): bir maçın istatistik, kadro ve eksikleri (sağlayıcı destekliyorsa).
* ``upcoming_details`` (low): takip edilen liglerde 90 dk içinde başlayacak maçların kadro ve
  eksikleri; son 6 saatte bitmiş, istatistiği olmayan maçların istatistikleri.
* ``standings`` / ``standings_active`` (low): bir ligin / takip edilen tüm liglerin puan durumu.
* ``season_backfill`` (low): bir ligin bir sezonundaki tüm maçlar (tarihsel veri).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api.db import Database
from mi_api.football.models import (
    Competition,
    Fixture,
    FixtureTeamStats,
    ProviderStatus,
    Season,
    SyncRun,
)
from mi_api.football.providers.base import (
    CapabilityNotSupported,
    FootballProvider,
    ProviderError,
    QuotaExceeded,
    QuotaInfo,
    SeasonData,
)
from mi_api.football.quota import Priority, QuotaBudget
from mi_api.football.store import FootballStore

log = logging.getLogger(__name__)

Job = Literal[
    "fixtures_date", "live", "fixture_details", "upcoming_details", "standings",
    "standings_active", "season_backfill",
]  # fmt: skip
JOBS: tuple[Job, ...] = (
    "fixtures_date", "live", "fixture_details", "upcoming_details", "standings",
    "standings_active", "season_backfill",
)  # fmt: skip
Trigger = Literal["schedule", "admin", "cli"]
PRIORITY: dict[Job, Priority] = {
    "fixtures_date": "high",
    "live": "high",
    "fixture_details": "low",
    "upcoming_details": "low",
    "standings": "low",
    "standings_active": "low",
    "season_backfill": "low",
}
LIVE_STATES = ("live", "halftime")


class JobInputError(ValueError):
    """İşin parametreleri geçersiz (ör. olmayan maç)."""


@dataclass
class RunResult:
    run_id: int
    job: Job
    status: Literal["succeeded", "failed", "skipped"]
    items: int = 0
    requests: int = 0
    message: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "job": self.job,
            "status": self.status,
            "items": self.items,
            "requests": self.requests,
            "message": self.message,
        }


class Skip(Exception):  # akış kontrolü
    """İş yapılmadan bitti (ör. canlı maç yok, sağlayıcı yapılandırılmamış)."""


class SyncService:
    def __init__(
        self,
        db: Database,
        provider: FootballProvider | None,
        *,
        provider_name: str,
        budget: QuotaBudget | None,
        clock: Callable[[], datetime],
    ) -> None:
        self.db = db
        self.provider = provider
        self.provider_name = provider_name
        self.budget = budget
        self.clock = clock

    async def observe_quota(self, info: QuotaInfo) -> None:
        if self.budget is not None:
            await self.budget.observe(info)
        async with self.db.session() as s:
            await self._status(s, quota=info)

    async def _status(
        self,
        s: AsyncSession,
        *,
        quota: QuotaInfo | None = None,
        success: bool = False,
        error: str | None = None,
    ) -> None:
        now = self.clock()
        values: dict[str, Any] = {"provider": self.provider_name}
        if quota is not None:
            values.update(
                daily_limit=quota.daily_limit,
                daily_remaining=quota.daily_remaining,
                minute_limit=quota.minute_limit,
                minute_remaining=quota.minute_remaining,
                observed_at=now,
            )
        if success:
            values["last_success_at"] = now
        if error is not None:
            values["last_error_at"] = now
            values["last_error"] = error[:1000]
        stmt = insert(ProviderStatus).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProviderStatus.provider],
            # Güncellenecek alan yoksa (yalnızca kayıt oluşturma) sağlayıcı adı yeniden yazılır.
            set_={k: stmt.excluded[k] for k in values if k != "provider"}
            or {"provider": stmt.excluded.provider},
        )
        await s.execute(stmt)

    async def run(self, job: Job, params: dict[str, Any], *, trigger: Trigger) -> RunResult:
        started = self.clock()
        async with self.db.session() as s:
            row = SyncRun(
                provider=self.provider_name,
                job=job,
                params=params,
                trigger=trigger,
                status="running",
                started_at=started,
            )
            s.add(row)
            await s.flush()
            run_id = row.id
        result = RunResult(run_id=run_id, job=job, status="succeeded")
        before = self.provider.requests_made if self.provider else 0
        if self.budget is not None:
            self.budget.priority = PRIORITY[job]
        try:
            if self.provider is None:
                raise Skip("Futbol veri sağlayıcısı yapılandırılmamış (M-G1)")
            handler: Callable[[dict[str, Any], RunResult], Awaitable[None]] = getattr(
                self, f"_job_{job}"
            )
            await handler(params, result)
            if result.notes:
                result.message = "; ".join(result.notes)
        except Skip as exc:
            result.status, result.message = "skipped", str(exc)
        except QuotaExceeded as exc:
            result.status, result.message = "skipped", f"Kota: {exc}"
        except JobInputError as exc:
            result.status, result.message = "failed", str(exc)
        except ProviderError as exc:
            result.status, result.message = "failed", str(exc)
            log.warning("Futbol senkronizasyonu başarısız: %s %s", job, exc)
        except Exception as exc:
            result.status, result.message = "failed", f"Beklenmeyen hata: {type(exc).__name__}"
            log.exception("Futbol senkronizasyonunda beklenmeyen hata: %s", job)
        result.requests = (self.provider.requests_made if self.provider else 0) - before
        async with self.db.session() as s:
            await s.execute(
                update(SyncRun)
                .where(SyncRun.id == run_id)
                .values(
                    status=result.status,
                    finished_at=self.clock(),
                    items=result.items,
                    requests=result.requests,
                    message=result.message,
                )
            )
            if self.provider is not None and result.requests:
                failed = result.status == "failed"
                await self._status(s, success=not failed, error=result.message if failed else None)
        return result

    # --- İşler -----------------------------------------------------------------------------------

    def _p(self) -> FootballProvider:
        if self.provider is None:  # run() zaten kontrol eder
            raise Skip("Futbol veri sağlayıcısı yapılandırılmamış (M-G1)")
        return self.provider

    async def _store_fixtures(self, fixtures: list[Any], result: RunResult) -> None:
        async with self.db.session() as s:
            store = FootballStore(s, self.provider_name, self.clock())
            for fx in fixtures:
                await store.fixture(fx)
        result.items += len(fixtures)

    async def _job_fixtures_date(self, params: dict[str, Any], result: RunResult) -> None:
        try:
            day = date.fromisoformat(str(params["date"]))
        except (KeyError, ValueError) as exc:
            raise JobInputError("Geçerli bir 'date' (YYYY-AA-GG) gerekli") from exc
        await self._store_fixtures(await self._p().fixtures_by_date(day), result)

    async def _job_live(self, params: dict[str, Any], result: RunResult) -> None:
        now = self.clock()
        async with self.db.session() as s:
            candidates = (
                await s.execute(
                    select(func.count())
                    .select_from(Fixture)
                    .where(
                        Fixture.provider == self.provider_name,
                        or_(
                            Fixture.status.in_(LIVE_STATES),
                            (Fixture.status.in_(("scheduled", "tbd")))
                            & (
                                Fixture.kickoff_at.between(
                                    now - timedelta(hours=3), now + timedelta(minutes=15)
                                )
                            ),
                        ),
                    )
                )
            ).scalar_one()
        if not candidates:
            raise Skip("Canlı veya başlamak üzere maç yok; istek atılmadı")
        live = await self._p().live_fixtures()
        await self._store_fixtures(live, result)
        # Canlı listesinden düşen (bitmiş) maçların son skorunu tek tek al.
        live_ids = {fx.external_id for fx in live}
        async with self.db.session() as s:
            dropped = (
                (
                    await s.execute(
                        select(Fixture.external_id).where(
                            Fixture.provider == self.provider_name,
                            Fixture.status.in_(LIVE_STATES),
                            Fixture.external_id.not_in(live_ids)
                            if live_ids
                            else Fixture.id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        for external_id in dropped:
            fx = await self._p().fixture(external_id)
            if fx is not None:
                await self._store_fixtures([fx], result)

    async def _fixture_by_id(self, fixture_id: Any) -> Fixture:
        try:
            internal = int(fixture_id)
        except (TypeError, ValueError) as exc:
            raise JobInputError("Geçerli bir 'fixture_id' gerekli") from exc
        async with self.db.session() as s:
            fixture = await s.get(Fixture, internal)
        if fixture is None or fixture.provider != self.provider_name:
            raise JobInputError(f"Maç bulunamadı: {fixture_id}")
        return fixture

    async def _details(
        self, fixture: Fixture, result: RunResult, *, stats: bool, pre: bool
    ) -> None:
        provider = self._p()
        caps = provider.capabilities
        parts: list[tuple[str, Callable[[], Awaitable[list[Any]]], str]] = []
        if stats and "team_stats" in caps:
            parts.append(
                ("team_stats", lambda: provider.team_stats(fixture.external_id), "team_stats")
            )
        if pre and "lineups" in caps:
            parts.append(("lineups", lambda: provider.lineups(fixture.external_id), "lineups"))
        if pre and "absences" in caps:
            parts.append(("absences", lambda: provider.absences(fixture.external_id), "absences"))
        if not parts:
            result.notes.append(f"{self.provider_name}: maç ayrıntısı desteklenmiyor")
            return
        for _, fetch, method in parts:
            try:
                rows = await fetch()
            except CapabilityNotSupported as exc:
                result.notes.append(str(exc))
                continue
            async with self.db.session() as s:
                store = FootballStore(s, self.provider_name, self.clock())
                result.items += await getattr(store, method)(fixture.id, rows)

    async def _job_fixture_details(self, params: dict[str, Any], result: RunResult) -> None:
        fixture = await self._fixture_by_id(params.get("fixture_id"))
        started = fixture.status in (*LIVE_STATES, "finished")
        await self._details(fixture, result, stats=started, pre=True)

    async def _job_upcoming_details(self, params: dict[str, Any], result: RunResult) -> None:
        now = self.clock()
        async with self.db.session() as s:
            active = (
                select(Season.id)
                .join(Competition, Competition.id == Season.competition_id)
                .where(Competition.is_active)
            )
            upcoming = (
                (
                    await s.execute(
                        select(Fixture)
                        .where(
                            Fixture.provider == self.provider_name,
                            Fixture.season_id.in_(active),
                            Fixture.status.in_(("scheduled", "tbd")),
                            Fixture.kickoff_at.between(now, now + timedelta(minutes=90)),
                        )
                        .order_by(Fixture.kickoff_at)
                        .limit(int(params.get("limit", 20)))
                    )
                )
                .scalars()
                .all()
            )
            finished = (
                (
                    await s.execute(
                        select(Fixture)
                        .where(
                            Fixture.provider == self.provider_name,
                            Fixture.season_id.in_(active),
                            Fixture.status == "finished",
                            Fixture.kickoff_at >= now - timedelta(hours=6),
                            ~exists().where(FixtureTeamStats.fixture_id == Fixture.id),
                        )
                        .order_by(Fixture.kickoff_at)
                        .limit(int(params.get("limit", 20)))
                    )
                )
                .scalars()
                .all()
            )
        if not upcoming and not finished:
            raise Skip("Ayrıntısı alınacak maç yok")
        for fx in upcoming:
            await self._details(fx, result, stats=False, pre=True)
        for fx in finished:
            await self._details(fx, result, stats=True, pre=False)

    async def _competition(self, competition_id: Any) -> Competition:
        try:
            internal = int(competition_id)
        except (TypeError, ValueError) as exc:
            raise JobInputError("Geçerli bir 'competition_id' gerekli") from exc
        async with self.db.session() as s:
            comp = await s.get(Competition, internal)
        if comp is None or comp.provider != self.provider_name:
            raise JobInputError(f"Lig bulunamadı: {competition_id}")
        return comp

    async def _latest_season_year(self, competition_id: int) -> int:
        async with self.db.session() as s:
            year = (
                await s.execute(
                    select(func.max(Season.year)).where(Season.competition_id == competition_id)
                )
            ).scalar_one_or_none()
        if year is None:
            raise JobInputError("Bu lig için sezon bilinmiyor; 'season' belirtin")
        return int(year)

    async def _standings_for(self, comp: Competition, season: int, result: RunResult) -> None:
        if "standings" not in self._p().capabilities:
            raise Skip(f"{self.provider_name}: puan durumu desteklenmiyor")
        rows = await self._p().standings(comp.external_id, season)
        async with self.db.session() as s:
            store = FootballStore(s, self.provider_name, self.clock())
            season_id = await store.season(
                comp.id, SeasonData(year=season, label=f"{season}/{(season + 1) % 100:02d}")
            )
            result.items += await store.standings(season_id, rows)

    async def _job_standings(self, params: dict[str, Any], result: RunResult) -> None:
        comp = await self._competition(params.get("competition_id"))
        season = params.get("season")
        year = int(season) if season is not None else await self._latest_season_year(comp.id)
        await self._standings_for(comp, year, result)

    async def _job_standings_active(self, params: dict[str, Any], result: RunResult) -> None:
        async with self.db.session() as s:
            comps = (
                (
                    await s.execute(
                        select(Competition).where(
                            Competition.provider == self.provider_name, Competition.is_active
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not comps:
            raise Skip("Takip edilen lig yok (yönetim panelinden etkinleştirin)")
        for comp in comps:
            try:
                await self._standings_for(comp, await self._latest_season_year(comp.id), result)
            except JobInputError as exc:
                result.notes.append(f"{comp.name}: {exc}")

    async def _job_season_backfill(self, params: dict[str, Any], result: RunResult) -> None:
        comp = await self._competition(params.get("competition_id"))
        try:
            season = int(params["season"])
        except (KeyError, TypeError, ValueError) as exc:
            raise JobInputError("Geçerli bir 'season' (yıl) gerekli") from exc
        await self._store_fixtures(
            await self._p().season_fixtures(comp.external_id, season), result
        )


def utc_today(now: datetime) -> date:
    return now.astimezone(UTC).date()
