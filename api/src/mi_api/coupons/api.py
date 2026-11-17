"""Kupon API'si ve sonuçlandırma.

Kullanıcı (oturum gerekli; abonelik kısıtı Faz 6'da):
* ``POST /v1/coupons/generate`` — otomatik kupon taslağı (kaydetmez)
* ``POST /v1/coupons`` — kuponu kaydeder. Olasılıklar **sunucuda** tahmin kayıtlarından yeniden
  hesaplanır; istemcinin gönderdiği olasılığa güvenilmez. Kayıt değiştirilemez.
* ``GET /v1/coupons`` / ``GET /v1/coupons/{id}`` — kendi kupon geçmişi

Yönetim:
* ``GET /admin/v1/coupons`` — ``coupons.read``: tüm kuponlar ve gerçekleşen/beklenen özet
* ``POST /admin/v1/coupons/settle`` — ``coupons.manage``: sonuçlandırmayı hemen çalıştırır

Sonuçlandırma: maç bittiğinde seçim 90' skoruna göre tutar/tutmaz; iptal veya yarıda kalan maç
"geçersiz" (void) olur. Bir seçim tutmazsa kupon kaybeder; geri kalanların hepsi tutar veya geçersiz
olursa kupon kazanır (hepsi geçersizse kupon geçersiz).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mi_api import audit
from mi_api.billing.plans import access_for, consume, plan_required
from mi_api.context import (
    DbDep,
    MetaDep,
    Principal,
    ServicesDep,
    UserDep,
    enforce_limit,
    require_permission,
)
from mi_api.coupons.engine import (
    MARKET_CODES,
    Candidate,
    CouponError,
    Leg,
    build,
    evaluate,
    fixture_joint,
    market,
    risk_text,
)
from mi_api.coupons.models import Coupon, CouponLeg
from mi_api.engage.notify import notify
from mi_api.errors import ApiError
from mi_api.football.api import TR
from mi_api.football.models import Competition, Fixture, Season, Team
from mi_api.ops import flags
from mi_api.predictions.models import Prediction
from mi_api.virtual.service import settle_tickets

DISCLAIMER = (
    "Kupon olasılıkları model tahminidir; kesin sonuç veya kazanç garantisi değildir. "
    "Platform gerçek bahis işlemi yapmaz."
)
ODDS_NOTE = "Lisanslı oran verisi bağlı değil: toplam oran ve beklenen değer (EV) hesaplanmaz."
REL_ORDER = {"low": 0, "medium": 1, "high": 2}
KICKOFF_MARGIN = timedelta(minutes=5)

Home = aliased(Team)
Away = aliased(Team)


class GenerateBody(BaseModel):
    day: date | None = Field(default=None, alias="date")
    profile: Literal["low", "balanced", "high"] = "balanced"
    size: int = Field(default=3, ge=1, le=10)
    competition_ids: list[int] | None = Field(default=None, max_length=50)
    markets: list[str] | None = Field(default=None, max_length=10)


class LegIn(BaseModel):
    prediction_id: int = Field(ge=1)
    market: str = Field(max_length=16)
    pick: str = Field(max_length=16)


class SaveBody(BaseModel):
    profile: Literal["low", "balanced", "high", "manual"] = "manual"
    legs: list[LegIn] = Field(min_length=1, max_length=20)
    params: dict[str, Any] = Field(default_factory=dict)


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=TR)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _info(fx: Fixture, home: Team, away: Team, comp: Competition) -> dict[str, Any]:
    return {
        "fixture_id": fx.id,
        "kickoff_at": fx.kickoff_at.isoformat(),
        "kickoff_local": fx.kickoff_at.astimezone(TR).isoformat(),
        "home": home.name,
        "away": away.name,
        "competition": {"id": comp.id, "name": comp.name},
    }


def _candidate_query() -> Any:
    latest = (
        select(Prediction.id)
        .ext(distinct_on(Prediction.fixture_id))
        .order_by(Prediction.fixture_id, Prediction.created_at.desc(), Prediction.id.desc())
    )
    return (
        select(Prediction, Fixture, Home, Away, Competition)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .join(Home, Home.id == Fixture.home_team_id)
        .join(Away, Away.id == Fixture.away_team_id)
        .join(Season, Season.id == Fixture.season_id)
        .join(Competition, Competition.id == Season.competition_id)
        .where(Prediction.id.in_(latest.subquery().select()))
    )


async def _candidates(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    competition_ids: list[int] | None,
) -> list[Candidate]:
    stmt = _candidate_query().where(
        Prediction.status == "published",
        Fixture.status.in_(("scheduled", "tbd")),
        Fixture.kickoff_at >= max(start, now + KICKOFF_MARGIN),
        Fixture.kickoff_at < end,
    )
    if competition_ids:
        stmt = stmt.where(Competition.id.in_(competition_ids))
    rows = (await db.execute(stmt.order_by(Fixture.kickoff_at))).all()
    return [
        Candidate(
            prediction_id=p.id,
            fixture_id=fx.id,
            probabilities=p.probabilities or {},
            reliability=p.reliability,
            info={
                **_info(fx, h, a, c),
                "model_version_id": p.model_version_id,
                "prediction_created_at": p.created_at.isoformat(),
            },
        )
        for p, fx, h, a, c in rows
    ]


def _draft(legs: list[tuple[Candidate, str, str, float]], profile: str) -> dict[str, Any]:
    engine_legs = [
        Leg(c.fixture_id, market(code, pick), c.probabilities) for c, code, pick, _ in legs
    ]
    ev = evaluate(engine_legs)
    weakest = min((c.reliability for c, *_ in legs), key=lambda r: REL_ORDER.get(r, 0))
    return {
        "profile": profile,
        "legs": [
            {
                "prediction_id": c.prediction_id,
                "market": code,
                "pick": pick,
                "label": market(code, pick).label,
                "probability": p,
                "reliability": c.reliability,
                **c.info,
            }
            for c, code, pick, p in legs
        ],
        **ev.as_dict(),
        "risk": risk_text(ev.joint_probability, len(legs), weakest),
        "odds": None,
        "odds_note": ODDS_NOTE,
        "disclaimer": DISCLAIMER,
    }


async def settle_coupons(db: AsyncSession, now: datetime) -> dict[str, int]:
    rows = (
        await db.execute(
            select(CouponLeg, Fixture)
            .join(Fixture, Fixture.id == CouponLeg.fixture_id)
            .where(
                CouponLeg.result == "pending",
                Fixture.status.in_(("finished", "cancelled", "abandoned")),
            )
            .with_for_update(of=CouponLeg)
        )
    ).all()
    legs_settled = 0
    touched: set[int] = set()
    for leg, fx in rows:
        if fx.status in ("cancelled", "abandoned"):
            leg.result = "void"
        else:
            if fx.ft_home is not None and fx.ft_away is not None:
                h, a = fx.ft_home, fx.ft_away
            elif (
                fx.status_detail in ("FT", "FINISHED")
                and fx.home_goals is not None
                and fx.away_goals is not None
            ):
                h, a = fx.home_goals, fx.away_goals
            else:
                continue  # 90' skoru bilinmiyor; beklemede kalır
            m = market(leg.market, leg.pick)
            if m.half:
                x, y = fx.ht_home, fx.ht_away
                if x is None or y is None or x > h or y > a:
                    # İY skoru bilinmiyor/tutarsız: seçim beklemede kalır; maç 3 günden eskiyse
                    # sağlayıcının veriyi düzeltmesi beklenmez, seçim geçersiz sayılır.
                    if fx.kickoff_at > now - timedelta(days=3):
                        continue
                    leg.result = "void"
                    legs_settled += 1
                    touched.add(leg.coupon_id)
                    continue
            else:
                x = y = -1
            leg.result = "won" if m.predicate(h, a, x, y) else "lost"
        legs_settled += 1
        touched.add(leg.coupon_id)
    await db.flush()
    coupons_settled = 0
    for coupon_id in touched:
        coupon = await db.get(Coupon, coupon_id, with_for_update=True)
        if coupon is None or coupon.status != "pending":
            continue
        results = (
            (await db.execute(select(CouponLeg.result).where(CouponLeg.coupon_id == coupon_id)))
            .scalars()
            .all()
        )
        if "lost" in results:
            coupon.status = "lost"
        elif "pending" in results:
            continue
        elif all(r == "void" for r in results):
            coupon.status = "void"
        else:
            coupon.status = "won"
        coupon.settled_at = now
        if coupon.user_id is not None:
            label = {"won": "tuttu", "lost": "tutmadı", "void": "geçersiz sayıldı"}[coupon.status]
            await notify(
                db,
                coupon.user_id,
                "coupon",
                f"Kuponunuz {label}",
                f"#{coupon.id} numaralı {coupon.legs_count} seçimlik kupon sonuçlandı.",
                now=now,
                link="/kuponlar",
                dedupe_key=f"coupon:{coupon.id}",
            )
        coupons_settled += 1
        await db.flush()
        # Bu kupona bağlı sanal biletler (Faz 5) aynı işlemde sonuçlanır.
        await settle_tickets(db, coupon, "void" in results, now)
    return {"legs": legs_settled, "coupons": coupons_settled}


async def coupon_view(db: AsyncSession, coupon: Coupon) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(CouponLeg, Fixture, Home, Away)
            .join(Fixture, Fixture.id == CouponLeg.fixture_id)
            .join(Home, Home.id == Fixture.home_team_id)
            .join(Away, Away.id == Fixture.away_team_id)
            .where(CouponLeg.coupon_id == coupon.id)
            .order_by(CouponLeg.position)
        )
    ).all()
    return {
        "id": coupon.id,
        "created_at": coupon.created_at.isoformat(),
        "profile": coupon.profile,
        "status": coupon.status,
        "settled_at": coupon.settled_at.isoformat() if coupon.settled_at else None,
        "joint_probability": coupon.joint_probability,
        "evaluation": coupon.evaluation,
        "legs": [
            {
                "position": leg.position,
                "fixture_id": leg.fixture_id,
                "home": h.name,
                "away": a.name,
                "kickoff_at": leg.kickoff_at.isoformat(),
                "label": leg.label,
                "market": leg.market,
                "pick": leg.pick,
                "probability": leg.probability,
                "reliability": leg.reliability,
                "result": leg.result,
                "score": {"home": fx.ft_home, "away": fx.ft_away}
                if fx.ft_home is not None
                else None,
            }
            for leg, fx, h, a in rows
        ],
        "odds_note": ODDS_NOTE,
        "disclaimer": DISCLAIMER,
    }


async def _resolve(
    db: AsyncSession, body: SaveBody, now: datetime
) -> tuple[dict[str, Any], list[tuple[Candidate, str, str, float]]]:
    """Seçimleri sunucuda tahmin kayıtlarından çözer ve kuponu değerlendirir (kaydetmez)."""
    ids = sorted({leg.prediction_id for leg in body.legs})
    rows = (await db.execute(_candidate_query().where(Prediction.id.in_(ids)))).all()
    by_id = {p.id: (p, fx, h, a, c) for p, fx, h, a, c in rows}
    legs: list[tuple[Candidate, str, str, float]] = []
    seen: set[tuple[int, str, str]] = set()
    for leg_in in body.legs:
        row = by_id.get(leg_in.prediction_id)
        if row is None:
            raise ApiError(
                422,
                "stale_prediction",
                "Tahmin bulunamadı veya maçın daha yeni bir tahmini var; kuponu yeniden oluşturun",
            )
        p, fx, h, a, c = row
        if p.status != "published" or not p.probabilities:
            raise ApiError(422, "abstained", "Model bu maç için tahmin yayımlamadı")
        if fx.status not in ("scheduled", "tbd") or fx.kickoff_at <= now + KICKOFF_MARGIN:
            raise ApiError(
                422, "kickoff_passed", f"{h.name} – {a.name} başlamış veya başlamak üzere"
            )
        if (p.id, leg_in.market, leg_in.pick) in seen:
            raise ApiError(422, "duplicate_leg", "Aynı seçim iki kez eklenemez")
        seen.add((p.id, leg_in.market, leg_in.pick))
        try:
            m = market(leg_in.market, leg_in.pick)
            prob = fixture_joint([Leg(fx.id, m, p.probabilities)])
        except CouponError as exc:
            raise ApiError(422, exc.code, str(exc)) from exc
        cand = Candidate(p.id, fx.id, p.probabilities, p.reliability, _info(fx, h, a, c))
        legs.append((cand, m.code, m.pick, prob))
    try:
        draft = _draft(legs, body.profile)
    except CouponError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    return draft, legs


def _check_plan(access: Any, body: SaveBody) -> None:
    if not access.allows("coupons.enabled"):
        raise plan_required("coupons.enabled")
    if len({leg.prediction_id for leg in body.legs}) > int(access.get("coupons.max_legs", 0)):
        raise ApiError(
            403,
            "plan_limit",
            f"Paketinizde kupon en fazla {access.get('coupons.max_legs')} maç olabilir",
        )


def create_coupons_router() -> APIRouter:
    router = APIRouter(tags=["coupons"])

    @router.post("/v1/coupons/generate")
    async def generate(
        body: GenerateBody, user: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        await enforce_limit(services, f"coupon_generate:user:{user.user.id}", 30, 600)
        await flags.require(db, "coupons_enabled")
        access = await access_for(db, user.user.id, services.clock())
        if not access.allows("coupons.enabled"):
            raise plan_required("coupons.enabled")
        if body.size > int(access.get("coupons.max_legs", 0)):
            raise ApiError(
                403,
                "plan_limit",
                f"Paketinizde kupon en fazla {access.get('coupons.max_legs')} maç olabilir",
            )
        await consume(
            db,
            user.user.id,
            "coupons.generate",
            access.get("coupons.daily_generate"),
            services.clock(),
        )
        if body.markets and set(body.markets) - MARKET_CODES:
            raise ApiError(422, "unknown_market", "Bilinmeyen piyasa filtresi")
        now = services.clock()
        day = body.day or now.astimezone(TR).date()
        start, end = _bounds(day)
        candidates = await _candidates(
            db, start=start, end=end, now=now, competition_ids=body.competition_ids
        )
        try:
            picks = build(
                candidates,
                profile=body.profile,
                size=body.size,
                markets=frozenset(body.markets) if body.markets else None,
            )
        except CouponError as exc:
            raise ApiError(422, exc.code, str(exc)) from exc
        draft = _draft(
            [(p.candidate, p.market.code, p.market.pick, p.probability) for p in picks],
            body.profile,
        )
        draft["params"] = {
            "date": day.isoformat(),
            "size": body.size,
            "competition_ids": body.competition_ids,
            "markets": body.markets,
        }
        draft["candidates_considered"] = len(candidates)
        return draft

    @router.post("/v1/coupons/preview")
    async def preview(
        body: SaveBody, user: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        """Kullanıcının seçtiği seçimlerle (maç sayfasından "kupona ekle") kupon önizlemesi:
        birleşik olasılık ve Monte Carlo doğrulaması. Kaydetmez."""
        await enforce_limit(services, f"coupon_preview:user:{user.user.id}", 120, 600)
        await flags.require(db, "coupons_enabled")
        _check_plan(await access_for(db, user.user.id, services.clock()), body)
        draft, _ = await _resolve(db, body, services.clock())
        return draft

    @router.post("/v1/coupons", status_code=201)
    async def save(
        body: SaveBody, user: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        await enforce_limit(services, f"coupon_save:user:{user.user.id}", 30, 600)
        await flags.require(db, "coupons_enabled")
        _check_plan(await access_for(db, user.user.id, services.clock()), body)
        now = services.clock()
        draft, legs = await _resolve(db, body, now)
        coupon = Coupon(
            user_id=user.user.id,
            created_at=now,
            first_kickoff_at=min(
                datetime.fromisoformat(leg["kickoff_at"]) for leg in draft["legs"]
            ),
            profile=body.profile,
            params={
                k: v
                for k, v in body.params.items()
                if k in ("date", "size", "competition_ids", "markets")
            },
            legs_count=len(legs),
            joint_probability=draft["joint_probability"],
            evaluation={
                k: draft[k]
                for k in ("joint_probability", "one_in", "monte_carlo", "assumption", "risk")
            },
            status="pending",
        )
        db.add(coupon)
        await db.flush()
        for i, leg in enumerate(draft["legs"]):
            db.add(
                CouponLeg(
                    coupon_id=coupon.id,
                    position=i + 1,
                    prediction_id=leg["prediction_id"],
                    fixture_id=leg["fixture_id"],
                    market=leg["market"],
                    pick=leg["pick"],
                    label=leg["label"],
                    probability=leg["probability"],
                    reliability=leg["reliability"],
                    kickoff_at=datetime.fromisoformat(leg["kickoff_at"]),
                )
            )
        await db.flush()
        await audit.record(
            db,
            "coupon.created",
            actor_type="user",
            actor_id=str(user.user.id),
            target_type="coupon",
            target_id=str(coupon.id),
            ip=meta.ip,
            details={"legs": len(legs), "profile": body.profile},
        )
        return await coupon_view(db, coupon)

    @router.get("/v1/coupons")
    async def my_coupons(
        user: UserDep,
        db: DbDep,
        services: ServicesDep,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ) -> dict[str, Any]:
        now = services.clock()
        access = await access_for(db, user.user.id, now)
        since = now - timedelta(days=int(access.get("history.days", 7)))
        coupons = (
            (
                await db.execute(
                    select(Coupon)
                    .where(Coupon.user_id == user.user.id, Coupon.created_at >= since)
                    .order_by(Coupon.created_at.desc(), Coupon.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return {"items": [await coupon_view(db, c) for c in coupons]}

    @router.get("/v1/coupons/{coupon_id}")
    async def my_coupon(coupon_id: int, user: UserDep, db: DbDep) -> dict[str, Any]:
        coupon = await db.get(Coupon, coupon_id)
        if coupon is None or coupon.user_id != user.user.id:
            raise ApiError(404, "not_found", "Kupon bulunamadı")
        return await coupon_view(db, coupon)

    @router.get("/admin/v1/coupons")
    async def admin_coupons(
        db: DbDep,
        _: Principal = Depends(require_permission("coupons.read")),
        status: Literal["pending", "won", "lost", "void"] | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        stmt = select(Coupon)
        if status:
            stmt = stmt.where(Coupon.status == status)
        coupons = (await db.execute(stmt.order_by(Coupon.id.desc()).limit(limit))).scalars().all()
        counts = dict(
            (await db.execute(select(Coupon.status, func.count()).group_by(Coupon.status))).all()
        )
        settled = (
            await db.execute(
                select(
                    func.count(),
                    func.avg(Coupon.joint_probability),
                    func.avg(case((Coupon.status == "won", 1.0), else_=0.0)),
                ).where(Coupon.status.in_(("won", "lost")))
            )
        ).one()
        return {
            "counts": counts,
            "settled": {
                "n": settled[0],
                "mean_predicted": settled[1],
                "observed_win_rate": settled[2],
                "note": (
                    "Beklenen ve gerçekleşen oran ancak "
                    "yeterli sayıda sonuçlanmış kuponla anlamlıdır."
                ),
            }
            if settled[0]
            else None,
            "items": [
                {
                    "id": c.id,
                    "user_id": str(c.user_id) if c.user_id else None,
                    "created_at": c.created_at.isoformat(),
                    "profile": c.profile,
                    "legs": c.legs_count,
                    "joint_probability": c.joint_probability,
                    "status": c.status,
                }
                for c in coupons
            ],
        }

    @router.post("/admin/v1/coupons/settle")
    async def admin_settle(
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = Depends(require_permission("coupons.manage")),
    ) -> dict[str, int]:
        result = await settle_coupons(db, services.clock())
        await audit.record(
            db,
            "admin.coupons_settled",
            actor_type="admin",
            actor_id=admin.actor_id,
            ip=meta.ip,
            details=result,
        )
        return result

    return router
