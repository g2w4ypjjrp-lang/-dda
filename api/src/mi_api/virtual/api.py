"""Sanal portföy API'si (``/v1/virtual``) ve yönetim özeti (``/admin/v1/virtual``).

Sanal birim (SB) gerçek para değildir; ödeme, çekim veya transfer uç noktası **yoktur**.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mi_api import audit
from mi_api.billing.plans import access_for, plan_required
from mi_api.context import (
    DbDep,
    MetaDep,
    Principal,
    ServicesDep,
    UserDep,
    enforce_limit,
    require_permission,
)
from mi_api.coupons.models import Coupon
from mi_api.errors import ApiError
from mi_api.football.api import TR
from mi_api.ops import flags
from mi_api.virtual import service
from mi_api.virtual.models import Ticket, VirtualAccount

SB = service.UNIT


class OpenBody(BaseModel):
    accept: Literal[True]  # "sanal birimin gerçek para olmadığını anladım"


class TicketBody(BaseModel):
    coupon_id: int = Field(ge=1)
    odds_source: Literal["model_fair", "user_entered"] = "model_fair"
    odds: Decimal | None = Field(default=None, ge=Decimal("1.01"), le=Decimal("1000"))


def account_view(a: VirtualAccount) -> dict[str, Any]:
    return {
        "balance_minor": a.balance_minor,
        "starting_balance_minor": a.starting_balance_minor,
        "unit": "SB",
        "minor_per_unit": SB,
        "settings": a.settings,
        "pending_settings": a.pending_settings,
        "pending_effective_at": a.pending_effective_at.isoformat()
        if a.pending_effective_at
        else None,
        "reset_count": a.reset_count,
        "last_reset_at": a.last_reset_at.isoformat() if a.last_reset_at else None,
        "disclaimer": service.DISCLAIMER,
    }


def ticket_view(t: Ticket) -> dict[str, Any]:
    ev = float(t.model_probability * float(t.odds) - 1) if t.odds_source == "user_entered" else None
    return {
        "id": t.id,
        "coupon_id": t.coupon_id,
        "created_at": t.created_at.isoformat(),
        "stake_minor": t.stake_minor,
        "odds": float(t.odds),
        "odds_source": t.odds_source,
        "odds_note": service.FAIR_NOTE if t.odds_source == "model_fair" else service.USER_ODDS_NOTE,
        "model_probability": t.model_probability,
        "model_ev": ev,
        "staking": t.staking,
        "status": t.status,
        "payout_minor": t.payout_minor,
        "settled_at": t.settled_at.isoformat() if t.settled_at else None,
    }


def create_virtual_router() -> APIRouter:
    router = APIRouter(tags=["virtual"])

    @router.post("/v1/virtual/account", status_code=201)
    async def open_account(
        body: OpenBody, user: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        await flags.require(db, "virtual_enabled")
        access = await access_for(db, user.user.id, services.clock())
        if not access.allows("virtual.enabled"):
            raise plan_required("virtual.enabled")
        account = await service.open_account(db, user.user.id, services.clock())
        await audit.record(
            db,
            "virtual.account_opened",
            actor_type="user",
            actor_id=user.actor_id,
            target_type="virtual_account",
            target_id=str(account.id),
            ip=meta.ip,
        )
        return account_view(account)

    @router.get("/v1/virtual/account")
    async def get_account(user: UserDep, db: DbDep, services: ServicesDep) -> dict[str, Any]:
        return account_view(await service.get_account(db, user.user.id, services.clock()))

    @router.put("/v1/virtual/settings")
    async def put_settings(
        body: service.Settings, user: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        now = services.clock()
        if body.method == "kelly" and not (await access_for(db, user.user.id, now)).allows(
            "virtual.kelly"
        ):
            raise plan_required("virtual.kelly")
        account = await service.get_account(db, user.user.id, now, lock=True)
        result = await service.update_settings(db, account, body, now)
        await audit.record(
            db,
            "virtual.settings_changed",
            actor_type="user",
            actor_id=user.actor_id,
            target_type="virtual_account",
            target_id=str(account.id),
            ip=meta.ip,
            details={"applied": result["applied"]},
        )
        return {**result, "account": account_view(account)}

    @router.post("/v1/virtual/tickets", status_code=201)
    async def place(
        body: TicketBody, user: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        await enforce_limit(services, f"virtual_ticket:user:{user.user.id}", 30, 600)
        await flags.require(db, "virtual_enabled")
        now = services.clock()
        account = await service.get_account(db, user.user.id, now, lock=True)
        coupon = await db.get(Coupon, body.coupon_id)
        if coupon is None or coupon.user_id != user.user.id:
            raise ApiError(404, "not_found", "Kupon bulunamadı")
        exists = (
            await db.execute(
                select(Ticket.id).where(
                    Ticket.account_id == account.id, Ticket.coupon_id == coupon.id
                )
            )
        ).scalar_one_or_none()
        if exists:
            raise ApiError(409, "ticket_exists", "Bu kupon için zaten sanal bilet var")
        ticket = await service.place_ticket(
            db, account, coupon, odds_source=body.odds_source, user_odds=body.odds, now=now
        )
        return {"ticket": ticket_view(ticket), "account": account_view(account)}

    @router.get("/v1/virtual/tickets")
    async def tickets(
        user: UserDep,
        db: DbDep,
        services: ServicesDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        account = await service.get_account(db, user.user.id, services.clock())
        rows = (
            (
                await db.execute(
                    select(Ticket)
                    .where(Ticket.account_id == account.id)
                    .order_by(Ticket.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return {"items": [ticket_view(t) for t in rows]}

    @router.get("/v1/virtual/report")
    async def get_report(
        user: UserDep,
        db: DbDep,
        services: ServicesDep,
        date_from: Annotated[date | None, Query(alias="from")] = None,
        date_to: Annotated[date | None, Query(alias="to")] = None,
    ) -> dict[str, Any]:
        account = await service.get_account(db, user.user.id, services.clock())
        start = (
            datetime.combine(date_from, time.min, tzinfo=TR).astimezone(UTC) if date_from else None
        )
        end = (
            (datetime.combine(date_to, time.min, tzinfo=TR) + timedelta(days=1)).astimezone(UTC)
            if date_to
            else None
        )
        return await service.report(db, account, start, end)

    @router.post("/v1/virtual/reset")
    async def reset(
        user: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        now = services.clock()
        account = await service.get_account(db, user.user.id, now, lock=True)
        await service.reset_account(db, account, now)
        await audit.record(
            db,
            "virtual.account_reset",
            actor_type="user",
            actor_id=user.actor_id,
            target_type="virtual_account",
            target_id=str(account.id),
            ip=meta.ip,
            details={"reset_count": account.reset_count},
        )
        return account_view(account)

    @router.get("/admin/v1/virtual")
    async def admin_summary(
        db: DbDep, _: Principal = Depends(require_permission("virtual.read"))
    ) -> dict[str, Any]:
        accounts, total = (
            await db.execute(
                select(func.count(), func.coalesce(func.sum(VirtualAccount.balance_minor), 0))
            )
        ).one()
        counts = dict(
            (await db.execute(select(Ticket.status, func.count()).group_by(Ticket.status))).all()
        )
        staked, returned = (
            await db.execute(
                select(
                    func.coalesce(func.sum(Ticket.stake_minor), 0),
                    func.coalesce(func.sum(Ticket.payout_minor), 0),
                ).where(Ticket.status.in_(("won", "lost")))
            )
        ).one()
        return {
            "accounts": accounts,
            "total_balance_minor": int(total),
            "tickets": counts,
            "settled_staked_minor": int(staked or 0),
            "simulated_roi": (int(returned or 0) - int(staked)) / int(staked) if staked else None,
            "label": "Simüle edilmiş — gerçek para değildir",
        }

    return router
