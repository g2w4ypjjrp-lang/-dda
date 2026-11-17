"""Paketler, ödeme, abonelik ve lisans API'si.

Kullanıcı (``/v1/billing``):
* ``GET plans`` — paketler, haklar, fiyatlar (fiyat yoksa satış kapalı) ve satış durumu
* ``GET me`` — etkin plan, haklar, bugünkü kullanım, abonelikler, siparişler
* ``POST checkout`` — sipariş + sağlayıcı ödeme sayfası (onay kutuları zorunlu)
* ``GET orders/{id}`` — kendi siparişinin durumu
* ``POST licenses/redeem`` — lisans anahtarı kullanma (hız sınırlı, başarısızlar denetime yazılır)
* ``GET/POST simulator/...`` — yalnızca geliştirme/test: test ödeme sayfası

Sağlayıcı bildirimi: ``POST /v1/billing/webhooks/{sağlayıcı}`` (köken denetimi yok, imza zorunlu).

Yönetim (``/admin/v1/billing``): plan hakları ve fiyatlar (``subscriptions.manage``), abonelikler,
siparişler ve iade (``finance.*``), lisanslar (``licenses.*``), gelir özeti (yalnızca gerçek
kayıtlar).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mi_api import audit
from mi_api.billing import service
from mi_api.billing.models import (
    License,
    Order,
    PaymentEventRow,
    Plan,
    PlanEntitlement,
    PlanPrice,
    Subscription,
)
from mi_api.billing.plans import (
    ENTITLEMENTS,
    LOCK_LABELS,
    access_for,
    usage_today,
    validate_entitlement,
)
from mi_api.billing.providers import (
    InvalidSignature,
    IyzicoProvider,
    ProviderError,
    SimulatorProvider,
)
from mi_api.context import (
    DbDep,
    MetaDep,
    Principal,
    ServicesDep,
    UserDep,
    enforce_limit,
    require_permission,
)
from mi_api.errors import ApiError
from mi_api.models import User
from mi_api.ops import approvals, flags

PAID_PLANS = ("PRO", "ELITE")
LEGAL_NOTE = (
    "Paketler analiz ve sanal simülasyon hizmetidir; gerçek bahis, kazanç veya para çekme içermez. "
    "Ödeme tek seferliktir ve dönem sonunda kendiliğinden yenilenmez."
)


def _perm(code: str) -> Any:
    return Depends(require_permission(code))


class BuyerIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=100)
    phone: str = Field(default="", max_length=20)
    address: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=60)


class CheckoutBody(BaseModel):
    plan: Literal["PRO", "ELITE"]
    period: Literal["monthly", "yearly"]
    buyer: BuyerIn
    accept_terms: Literal[True]
    accept_distance_sales: Literal[True]


class RedeemBody(BaseModel):
    key: str = Field(min_length=10, max_length=40)


class SimulatorBody(BaseModel):
    token: str = Field(min_length=10, max_length=120)
    outcome: Literal["success", "fail"]


class EntitlementsBody(BaseModel):
    values: dict[str, bool | int] = Field(min_length=1, max_length=len(ENTITLEMENTS))


class PriceBody(BaseModel):
    period: Literal["monthly", "yearly"]
    amount_minor: int = Field(ge=100, le=100_000_000)
    currency: Literal["TRY"] = "TRY"


class GrantBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    plan: Literal["PRO", "ELITE"]
    days: int = Field(ge=1, le=3660)
    note: str | None = Field(default=None, max_length=200)


class LicenseBody(BaseModel):
    plan: Literal["PRO", "ELITE"]
    duration_days: int = Field(ge=1, le=3660)
    count: int = Field(default=1, ge=1, le=100)
    max_activations: int = Field(default=1, ge=1, le=10_000)
    redeem_days: int = Field(default=90, ge=1, le=730)
    note: str | None = Field(default=None, max_length=200)


# --- Görünümler -----------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def order_view(o: Order) -> dict[str, Any]:
    return {
        "id": str(o.public_id),
        "number": o.id,
        "plan": o.plan_code,
        "period": o.period,
        "amount_minor": o.amount_minor,
        "currency": o.currency,
        "status": o.status,
        "provider": o.provider,
        "test_mode": o.test_mode,
        "created_at": o.created_at.isoformat(),
        "paid_at": _iso(o.paid_at),
        "refunded_at": _iso(o.refunded_at),
    }


def subscription_view(s: Subscription, now: datetime) -> dict[str, Any]:
    return {
        "id": s.id,
        "plan": s.plan_code,
        "status": s.status,
        "source": s.source,
        "started_at": s.started_at.isoformat(),
        "current_period_end": s.current_period_end.isoformat(),
        "in_effect": s.status in ("active", "canceled")
        and s.started_at <= now < s.current_period_end,
        "canceled_at": _iso(s.canceled_at),
    }


def license_view(lic: License) -> dict[str, Any]:
    return {
        "id": lic.id,
        "hint": f"MI-…-{lic.key_hint}",
        "plan": lic.plan_code,
        "duration_days": lic.duration_days,
        "max_activations": lic.max_activations,
        "activations_count": lic.activations_count,
        "status": lic.status,
        "redeem_before": lic.redeem_before.isoformat(),
        "created_at": lic.created_at.isoformat(),
        "revoked_at": _iso(lic.revoked_at),
        "note": lic.note,
    }


async def plans_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    plans = (await db.execute(select(Plan).where(Plan.is_public).order_by(Plan.sort))).scalars()
    ents = (await db.execute(select(PlanEntitlement))).scalars().all()
    prices = (await db.execute(select(PlanPrice).where(PlanPrice.active))).scalars().all()
    out = []
    for p in plans:
        out.append(
            {
                "code": p.code,
                "name": p.name,
                "tagline": p.tagline,
                "entitlements": {e.key: e.value for e in ents if e.plan_code == p.code},
                "prices": {
                    x.period: {"id": x.id, "amount_minor": x.amount_minor, "currency": x.currency}
                    for x in prices
                    if x.plan_code == p.code
                },
            }
        )
    return out


def _sales(services: Any) -> dict[str, Any]:
    cfg = services.settings
    return {
        "open": cfg.payment_provider != "none",
        "provider": cfg.payment_provider if cfg.payment_provider != "none" else None,
        "test_mode": cfg.payment_provider == "simulator" or cfg.payments_test_mode,
    }


def _provider(request: Request, services: Any) -> Any:
    provider = service.provider_for(services.settings, request.app.state.payment_transport)
    if provider is None:
        raise ApiError(503, "sales_closed", "Ödeme şu anda kapalı; satış henüz başlamadı")
    return provider


# --- Kullanıcı ------------------------------------------------------------------------------------


def create_billing_router() -> APIRouter:
    router = APIRouter(tags=["billing"])

    @router.get("/v1/billing/plans")
    async def plans(db: DbDep, services: ServicesDep) -> dict[str, Any]:
        return {
            "plans": await plans_catalog(db),
            "labels": LOCK_LABELS,
            "sales": _sales(services),
            "note": LEGAL_NOTE,
        }

    @router.get("/v1/billing/me")
    async def me(user: UserDep, db: DbDep, services: ServicesDep) -> dict[str, Any]:
        now = services.clock()
        access = await access_for(db, user.user.id, now)
        subs = (
            (
                await db.execute(
                    select(Subscription)
                    .where(Subscription.user_id == user.user.id)
                    .order_by(Subscription.created_at.desc(), Subscription.id.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        orders = (
            await db.execute(
                select(Order)
                .where(Order.user_id == user.user.id)
                .order_by(Order.created_at.desc(), Order.id.desc())
                .limit(20)
            )
        ).scalars()
        current = (
            await db.get(Subscription, access.subscription_id) if access.subscription_id else None
        )
        return {
            "plan": access.plan,
            "entitlements": access.values,
            "usage_today": await usage_today(db, user.user.id, now),
            "current": subscription_view(current, now) if current else None,
            "subscriptions": [subscription_view(s, now) for s in subs],
            "orders": [order_view(o) for o in orders],
            "sales": _sales(services),
        }

    @router.post("/v1/billing/checkout", status_code=201)
    async def checkout(
        body: CheckoutBody,
        request: Request,
        user: UserDep,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
    ) -> dict[str, Any]:
        await enforce_limit(services, f"checkout:user:{user.user.id}", 10, 3600)
        await flags.require(db, "sales_enabled")
        if user.user.email_verified_at is None:
            raise ApiError(
                403, "email_unverified", "Satın almadan önce e-posta adresinizi doğrulayın"
            )
        provider = _provider(request, services)
        now = services.clock()
        order, redirect_url = await service.create_order(
            db,
            settings=services.settings,
            provider=provider,
            user_id=user.user.id,
            email=user.user.email,
            plan=body.plan,
            period=body.period,
            buyer=body.buyer.model_dump(),
            ip=meta.ip,
            consent={"terms": True, "distance_sales": True, "at": now.isoformat(), "ip": meta.ip},
            now=now,
        )
        await audit.record(
            db,
            "billing.checkout_started",
            actor_type="user",
            actor_id=user.actor_id,
            target_type="order",
            target_id=str(order.id),
            ip=meta.ip,
            details={"plan": order.plan_code, "period": order.period, "provider": order.provider},
        )
        return {"order": order_view(order), "redirect_url": redirect_url}

    @router.get("/v1/billing/orders/{public_id}")
    async def get_order(public_id: uuid.UUID, user: UserDep, db: DbDep) -> dict[str, Any]:
        order = (
            await db.execute(select(Order).where(Order.public_id == public_id))
        ).scalar_one_or_none()
        if order is None or order.user_id != user.user.id:
            raise ApiError(404, "not_found", "Sipariş bulunamadı")
        return order_view(order)

    @router.post("/v1/billing/licenses/redeem")
    async def redeem(
        body: RedeemBody, user: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        await enforce_limit(services, f"license:user:{user.user.id}", 5, 900)
        if meta.ip:
            await enforce_limit(services, f"license:ip:{meta.ip}", 20, 3600)
        now = services.clock()
        try:
            sub = await service.redeem_license(
                db, services.settings, user_id=user.user.id, key=body.key, ip=meta.ip, now=now
            )
        except ApiError as exc:
            if exc.code == "invalid_license":
                await audit.record(
                    db,
                    "billing.license_redeem_failed",
                    actor_type="user",
                    actor_id=user.actor_id,
                    ip=meta.ip,
                    user_agent=meta.user_agent,
                )
            raise
        await audit.record(
            db,
            "billing.license_redeemed",
            actor_type="user",
            actor_id=user.actor_id,
            target_type="license",
            target_id=str(sub.license_id),
            ip=meta.ip,
            details={"plan": sub.plan_code, "subscription_id": sub.id},
        )
        return {"subscription": subscription_view(sub, now)}

    # --- Sağlayıcı bildirimleri ------------------------------------------------------------------

    @router.post("/v1/billing/webhooks/{name}", response_model=None)
    async def webhook(name: str, request: Request, db: DbDep, services: ServicesDep) -> Response:
        provider = service.provider_for(services.settings, request.app.state.payment_transport)
        if provider is None or provider.name != name:
            raise ApiError(404, "not_found", "Bilinmeyen ödeme sağlayıcısı")
        body = await request.body()
        now = services.clock()
        if isinstance(provider, IyzicoProvider):
            return await _iyzico_return(db, provider, body, services, now)
        headers = {k.lower(): v for k, v in request.headers.items()}
        result = await service.handle_webhook(db, provider, headers, body, now)
        await audit.record(
            db,
            f"billing.webhook_{result}",
            actor_type="webhook",
            actor_id=provider.name,
            details={"provider": provider.name},
        )
        if result == "invalid_signature":
            raise ApiError(400, "invalid_signature", "İmza doğrulanamadı", commit=True)
        if provider.name == "paytr":
            return PlainTextResponse("OK")  # PayTR yalnızca düz "OK" yanıtını kabul eder
        return Response(content=f'{{"result":"{result}"}}', media_type="application/json")

    async def _iyzico_return(
        db: AsyncSession, provider: IyzicoProvider, body: bytes, services: Any, now: datetime
    ) -> Response:
        """iyzico tarayıcıyı ``token`` ile geri yollar; sonuç sağlayıcıdan imzalı istekle alınır."""
        from urllib.parse import parse_qs

        token = (parse_qs(body.decode("utf-8", "replace")).get("token") or [""])[0]
        target = f"{services.settings.public_web_url}/odeme/sonuc"
        try:
            event = await provider.retrieve(token) if token else None
        except (InvalidSignature, ProviderError):
            event = None
        if event is None:
            await service.record_event(
                db,
                provider="iyzico",
                event=None,
                body=body,
                valid=False,
                result="invalid_signature",
                now=now,
            )
            return RedirectResponse(f"{target}?hata=dogrulanamadi", status_code=303)
        try:
            async with db.begin_nested():
                result = await service.apply_event(db, "iyzico", event, body, now)
        except IntegrityError:
            result = "duplicate"
        await audit.record(
            db,
            f"billing.webhook_{result}",
            actor_type="webhook",
            actor_id="iyzico",
            details={"provider": "iyzico"},
        )
        return RedirectResponse(f"{target}?siparis={event.order_ref}", status_code=303)

    # --- Test ödeme sayfası (yalnızca geliştirme/test) ------------------------------------------

    async def _sim_order(
        request: Request, services: Any, db: AsyncSession, token: str, user: Principal
    ) -> tuple[SimulatorProvider, Order]:
        provider = _provider(request, services)
        if not isinstance(provider, SimulatorProvider):
            raise ApiError(404, "not_found", "Test ödeme sayfası kapalı")
        try:
            order_id = provider.open_session(token)
        except InvalidSignature as exc:
            raise ApiError(400, "invalid_session", "Test ödeme oturumu geçersiz") from exc
        order = await service.find_order(db, order_id)
        if order is None or order.user_id != user.user.id:
            raise ApiError(404, "not_found", "Sipariş bulunamadı")
        return provider, order

    @router.get("/v1/billing/simulator/session")
    async def sim_session(
        request: Request,
        token: Annotated[str, Query(max_length=120)],
        user: UserDep,
        db: DbDep,
        services: ServicesDep,
    ) -> dict[str, Any]:
        _, order = await _sim_order(request, services, db, token, user)
        return {"order": order_view(order), "test_mode": True}

    @router.post("/v1/billing/simulator/complete")
    async def sim_complete(
        body: SimulatorBody, request: Request, user: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        provider, order = await _sim_order(request, services, db, body.token, user)
        if order.status != "pending":
            raise ApiError(409, "order_closed", "Bu sipariş zaten sonuçlandı")
        payload = provider.build_webhook(
            order_id=str(order.public_id),
            outcome=body.outcome,
            amount_minor=order.amount_minor,
            currency=order.currency,
        )
        # Gerçek bildirim yoluyla aynı kod: imza üretilir ve doğrulanır.
        headers = {"x-simulator-signature": provider.sign(payload)}
        result = await service.handle_webhook(db, provider, headers, payload, services.clock())
        await audit.record(
            db,
            f"billing.webhook_{result}",
            actor_type="webhook",
            actor_id="simulator",
            target_type="order",
            target_id=str(order.id),
            details={"provider": "simulator"},
        )
        await db.refresh(order)
        return {"result": result, "order": order_view(order)}

    router.include_router(create_billing_admin_router())
    return router


# --- Yönetim --------------------------------------------------------------------------------------


async def _plan(db: AsyncSession, code: str) -> Plan:
    plan = await db.get(Plan, code)
    if plan is None:
        raise ApiError(404, "not_found", "Paket bulunamadı")
    return plan


def create_billing_admin_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1/billing", tags=["admin-billing"])

    @router.get("/plans")
    async def admin_plans(
        db: DbDep, services: ServicesDep, _: Principal = _perm("subscriptions.read")
    ) -> dict[str, Any]:
        return {
            "plans": await plans_catalog(db),
            "entitlement_keys": {k: v[0].__name__ for k, v in ENTITLEMENTS.items()},
            "labels": LOCK_LABELS,
            "sales": _sales(services),
        }

    @router.put("/plans/{code}/entitlements")
    async def set_entitlements(
        code: str,
        body: EntitlementsBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("subscriptions.manage"),
    ) -> dict[str, Any]:
        await _plan(db, code)
        now = services.clock()
        changes = {}
        for key, value in body.values.items():
            clean = validate_entitlement(key, value)
            row = await db.get(PlanEntitlement, (code, key))
            before = row.value if row else None
            if row is None:
                db.add(PlanEntitlement(plan_code=code, key=key, value=clean, updated_at=now))
            else:
                row.value = clean
                row.updated_at = now
            changes[key] = {"from": before, "to": clean}
        await audit.record(
            db,
            "billing.entitlements_changed",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="plan",
            target_id=code,
            ip=meta.ip,
            details={"changes": changes},
        )
        await db.flush()
        return {"plans": await plans_catalog(db)}

    @router.put("/plans/{code}/prices")
    async def set_price(
        code: str,
        body: PriceBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("subscriptions.manage"),
    ) -> dict[str, Any]:
        if code not in PAID_PLANS:
            raise ApiError(422, "invalid_plan", "Yalnızca PRO ve ELITE fiyatlandırılabilir")
        now = services.clock()
        await db.execute(
            update(PlanPrice)
            .where(PlanPrice.plan_code == code, PlanPrice.period == body.period, PlanPrice.active)
            .values(active=False)
        )
        db.add(
            PlanPrice(
                plan_code=code,
                period=body.period,
                amount_minor=body.amount_minor,
                currency=body.currency,
                active=True,
                created_at=now,
                created_by=admin.user.id,
            )
        )
        await db.flush()
        await audit.record(
            db,
            "billing.price_set",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="plan",
            target_id=code,
            ip=meta.ip,
            details={
                "period": body.period,
                "amount_minor": body.amount_minor,
                "currency": body.currency,
            },
        )
        return {"plans": await plans_catalog(db)}

    @router.delete("/plans/{code}/prices/{period}")
    async def close_price(
        code: str,
        period: Literal["monthly", "yearly"],
        db: DbDep,
        meta: MetaDep,
        admin: Principal = _perm("subscriptions.manage"),
    ) -> dict[str, Any]:
        await db.execute(
            update(PlanPrice)
            .where(PlanPrice.plan_code == code, PlanPrice.period == period, PlanPrice.active)
            .values(active=False)
        )
        await audit.record(
            db,
            "billing.price_closed",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="plan",
            target_id=code,
            ip=meta.ip,
            details={"period": period},
        )
        return {"plans": await plans_catalog(db)}

    @router.get("/subscriptions")
    async def list_subscriptions(
        db: DbDep,
        services: ServicesDep,
        status: Annotated[str | None, Query(max_length=10)] = None,
        plan: Annotated[str | None, Query(max_length=16)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        _: Principal = _perm("subscriptions.read"),
    ) -> dict[str, Any]:
        stmt = select(Subscription, User.email).join(User, User.id == Subscription.user_id)
        if status:
            stmt = stmt.where(Subscription.status == status)
        if plan:
            stmt = stmt.where(Subscription.plan_code == plan)
        rows = (await db.execute(stmt.order_by(Subscription.id.desc()).limit(limit))).all()
        now = services.clock()
        return {"items": [{**subscription_view(s, now), "email": e} for s, e in rows]}

    @router.post("/subscriptions/grant", status_code=201)
    async def grant(
        body: GrantBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("subscriptions.manage"),
    ) -> dict[str, Any]:
        user = (
            await db.execute(
                select(User).where(func.lower(User.email) == body.email.strip().lower())
            )
        ).scalar_one_or_none()
        if user is None:
            raise ApiError(404, "not_found", "Kullanıcı bulunamadı")
        now = services.clock()
        sub = await service.grant_subscription(
            db,
            user_id=user.id,
            plan=body.plan,
            days=body.days,
            source="admin",
            now=now,
            granted_by=admin.user.id,
        )
        await audit.record(
            db,
            "billing.subscription_granted",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="user",
            target_id=str(user.id),
            ip=meta.ip,
            details={
                "plan": body.plan,
                "days": body.days,
                "note": body.note,
                "subscription_id": sub.id,
            },
        )
        return subscription_view(sub, now)

    @router.post("/subscriptions/{sub_id}/revoke")
    async def revoke(
        sub_id: int,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("subscriptions.manage"),
    ) -> dict[str, Any]:
        sub = await db.get(Subscription, sub_id, with_for_update=True)
        if sub is None:
            raise ApiError(404, "not_found", "Abonelik bulunamadı")
        if sub.status not in ("active", "canceled"):
            raise ApiError(409, "not_active", "Abonelik zaten sonlanmış")
        now = services.clock()
        sub.status = "revoked"
        sub.canceled_at = now
        await audit.record(
            db,
            "billing.subscription_revoked",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="subscription",
            target_id=str(sub.id),
            ip=meta.ip,
        )
        return subscription_view(sub, now)

    @router.get("/orders")
    async def list_orders(
        db: DbDep,
        status: Annotated[str | None, Query(max_length=12)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        _: Principal = _perm("finance.read"),
    ) -> dict[str, Any]:
        stmt = select(Order, User.email).join(User, User.id == Order.user_id)
        if status:
            stmt = stmt.where(Order.status == status)
        rows = (await db.execute(stmt.order_by(Order.id.desc()).limit(limit))).all()
        return {
            "items": [
                {**order_view(o), "email": e, "note": o.note, "refund_ref": o.refund_ref}
                for o, e in rows
            ]
        }

    @router.post("/orders/{number}/refund", response_model=None)
    async def refund(
        number: int,
        request: Request,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("finance.refund"),
    ) -> dict[str, Any] | JSONResponse:
        """İade. Dört göz kuralı açıksa 202 + onay talebi döner (``ops.approvals``)."""
        order = await db.get(Order, number)
        if order is None:
            raise ApiError(404, "not_found", "Sipariş bulunamadı")
        if order.status != "paid" or not order.provider_payment_id:
            raise ApiError(409, "not_refundable", "Yalnızca ödenmiş sipariş iade edilebilir")
        ctx = approvals.Ctx(
            db, services, request.app.state.payment_transport, admin.user.id, meta.ip
        )
        done = await approvals.submit(
            ctx,
            admin,
            "billing.refund",
            target=f"order:{order.id}",
            summary=f"Sipariş #{order.id} iadesi ({order.amount_minor / 100:.2f} {order.currency})",
            payload={"order": order.id},
        )
        if isinstance(done, approvals.Pending):
            return JSONResponse(done.body(), status_code=202)
        await db.refresh(order)
        return order_view(order)

    @router.get("/licenses")
    async def list_licenses(
        db: DbDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        _: Principal = _perm("licenses.read"),
    ) -> dict[str, Any]:
        rows = (
            await db.execute(select(License).order_by(License.id.desc()).limit(limit))
        ).scalars()
        return {"items": [license_view(x) for x in rows]}

    @router.post("/licenses", status_code=201)
    async def create_licenses(
        body: LicenseBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("licenses.manage"),
    ) -> dict[str, Any]:
        issued = await service.issue_licenses(
            db,
            services.settings,
            plan=body.plan,
            duration_days=body.duration_days,
            count=body.count,
            max_activations=body.max_activations,
            redeem_days=body.redeem_days,
            created_by=admin.user.id,
            note=body.note,
            now=services.clock(),
        )
        await audit.record(
            db,
            "billing.licenses_issued",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="license",
            target_id=",".join(str(lic.id) for lic, _ in issued),
            ip=meta.ip,
            details={"plan": body.plan, "count": body.count, "duration_days": body.duration_days},
        )
        return {
            "items": [{**license_view(lic), "key": key} for lic, key in issued],
            "warning": "Anahtarlar yalnızca şimdi gösterilir; güvenli bir yere kaydedin.",
        }

    @router.post("/licenses/{license_id}/revoke")
    async def revoke_license(
        license_id: int,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("licenses.manage"),
    ) -> dict[str, Any]:
        lic = await db.get(License, license_id, with_for_update=True)
        if lic is None:
            raise ApiError(404, "not_found", "Lisans bulunamadı")
        if lic.status == "revoked":
            raise ApiError(409, "already_revoked", "Lisans zaten iptal edilmiş")
        lic.status = "revoked"
        lic.revoked_at = services.clock()
        await audit.record(
            db,
            "billing.license_revoked",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="license",
            target_id=str(lic.id),
            ip=meta.ip,
        )
        return license_view(lic)

    @router.get("/summary")
    async def summary(
        db: DbDep, services: ServicesDep, _: Principal = _perm("finance.read")
    ) -> dict[str, Any]:
        return await billing_summary(db, services.clock())

    return router


async def billing_summary(db: AsyncSession, now: datetime) -> dict[str, Any]:
    """Yalnızca gerçek sipariş/abonelik kayıtlarından. Kayıt yoksa ``None`` (uydurma metrik yok)."""
    since = now - timedelta(days=30)
    Renewed = aliased(Subscription)
    revenue: dict[str, dict[str, int]] = {}
    for currency, status, total, count in (
        await db.execute(
            select(Order.currency, Order.status, func.sum(Order.amount_minor), func.count())
            .where(Order.status.in_(("paid", "refunded")), Order.test_mode.is_(False))
            .group_by(Order.currency, Order.status)
        )
    ).all():
        bucket = revenue.setdefault(currency, {"gross_minor": 0, "refunded_minor": 0, "orders": 0})
        bucket["gross_minor"] += int(total)
        bucket["orders"] += int(count)
        if status == "refunded":
            bucket["refunded_minor"] += int(total)
    for bucket in revenue.values():
        bucket["net_minor"] = bucket["gross_minor"] - bucket["refunded_minor"]

    # MRR: canlı (test olmayan) ödemeyle alınmış ve şu an geçerli aboneliklerin aylık karşılığı.
    live = (
        await db.execute(
            select(Order.amount_minor, Order.period, Order.currency)
            .join(Subscription, Subscription.order_id == Order.id)
            .where(
                Order.test_mode.is_(False),
                Order.status == "paid",
                Subscription.status.in_(("active", "canceled")),
                Subscription.started_at <= now,
                Subscription.current_period_end > now,
            )
        )
    ).all()
    mrr: dict[str, int] = {}
    for amount, period, currency in live:
        mrr[currency] = mrr.get(currency, 0) + (amount if period == "monthly" else amount // 12)

    paying_30 = (
        await db.execute(
            select(func.count(func.distinct(Order.user_id)), func.sum(Order.amount_minor)).where(
                Order.status == "paid", Order.test_mode.is_(False), Order.paid_at >= since
            )
        )
    ).one()
    ended = (
        await db.execute(
            select(func.count(func.distinct(Subscription.user_id))).where(
                Subscription.source == "payment",
                Subscription.current_period_end.between(since, now),
                ~select(Renewed.id)
                .where(
                    Renewed.user_id == Subscription.user_id,
                    Renewed.status.in_(("active", "canceled")),
                    Renewed.current_period_end > now,
                )
                .exists(),
            )
        )
    ).scalar_one()
    base = (
        await db.execute(
            select(func.count(func.distinct(Subscription.user_id))).where(
                Subscription.source == "payment",
                Subscription.started_at <= since,
                Subscription.current_period_end > since,
            )
        )
    ).scalar_one()
    active = (
        await db.execute(
            select(Subscription.plan_code, Subscription.source, func.count())
            .where(
                Subscription.status.in_(("active", "canceled")),
                Subscription.started_at <= now,
                Subscription.current_period_end > now,
            )
            .group_by(Subscription.plan_code, Subscription.source)
        )
    ).all()
    events = (
        await db.execute(
            select(PaymentEventRow.result, func.count())
            .where(PaymentEventRow.received_at >= since)
            .group_by(PaymentEventRow.result)
        )
    ).all()
    review = (
        await db.execute(select(func.count()).select_from(Order).where(Order.status == "review"))
    ).scalar_one()
    return {
        "revenue": revenue or None,
        "mrr_minor": mrr or None,
        "arr_minor": {c: v * 12 for c, v in mrr.items()} or None,
        "arpu_30d_minor": int(paying_30[1]) // int(paying_30[0]) if paying_30[0] else None,
        "churn_30d": round(ended / base, 4) if base else None,
        "active_subscriptions": [{"plan": p, "source": s, "count": n} for p, s, n in active],
        "payment_events_30d": {str(r): int(n) for r, n in events},
        "orders_in_review": review,
        "note": "Test modundaki ödemeler gelir metriklerine dahil edilmez.",
    }
