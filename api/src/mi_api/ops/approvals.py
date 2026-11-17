# ruff: noqa: E501
"""Dört göz onayı: kritik işlemler ikinci bir yöneticinin onayıyla yürütülür.

``dual_control`` bayrağı açıkken aşağıdaki işlemler hemen yürütülmez; bir onay talebi açılır
(HTTP 202). Talebi yalnızca **başka** bir yönetici onaylayabilir; onaylayanın aynı izne sahip olması
ve hassas izinlerde son dakikalarda yeniden doğrulama yapmış olması gerekir. Onayda işlem, o anki
durum yeniden denetlenerek yürütülür (talep ile onay arasında durum değişmiş olabilir); hata olursa
talep ``failed`` olarak kapanır ve hiçbir yan etki kalmaz (kayıt noktası geri alınır).

İşlemler:

* ``billing.refund`` — ödenmiş siparişi iade et (``finance.refund``)
* ``billing.review`` — incelemedeki siparişi onayla ya da iade et (``finance.refund``)
* ``roles.set`` — kullanıcının yönetici rollerini değiştir (``roles.assign``)
* ``flags.dual_control_off`` — dört göz kuralını kapat (``flags.manage``); kural tek kişiyle
  kapatılıp ardından tek kişiyle iade yapılamasın diye

Talep 24 saat içinde karara bağlanmazsa ``expired`` olur. Talep sahibi bekleyen talebini iptal
edebilir. Karara bağlanmış talep veritabanı tetikleyicisiyle değiştirilemez ve silinemez.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api import audit, rbac
from mi_api.billing import service as billing
from mi_api.billing.models import Order
from mi_api.billing.providers import ProviderError
from mi_api.context import Principal, Services, reauth_fresh, revoke_sessions, roles_of
from mi_api.errors import ApiError, forbidden
from mi_api.models import User, UserRole
from mi_api.ops.models import ApprovalRequest, FeatureFlag

TTL = timedelta(hours=24)


@dataclass(frozen=True)
class Ctx:
    """Yürütme bağlamı. ``actor`` işlemi fiilen yürüten yöneticidir (onay akışında onaylayan)."""

    db: AsyncSession
    services: Services
    transport: Any
    actor: uuid.UUID
    ip: str | None
    approval_id: int | None = None

    def details(self, extra: dict[str, Any]) -> dict[str, Any]:
        return extra | ({"approval_id": self.approval_id} if self.approval_id else {})


Executor = Callable[[Ctx, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Action:
    permission: str
    label: str
    run: Executor


@dataclass(frozen=True)
class Pending:
    """Onaya gönderildi; ``id`` talep numarası."""

    id: int
    expires_at: datetime

    def body(self) -> dict[str, Any]:
        return {
            "approval": {
                "id": self.id,
                "status": "pending",
                "expires_at": self.expires_at.isoformat(),
            },
            "detail": "Dört göz kuralı açık: işlem ikinci bir yöneticinin onayına gönderildi.",
        }


# --- Yürütücüler --------------------------------------------------------------------------------


async def _order(db: AsyncSession, number: int) -> Order:
    order = await db.get(Order, number, with_for_update=True)
    if order is None:
        raise ApiError(404, "not_found", "Sipariş bulunamadı")
    return order


def _provider(ctx: Ctx, order: Order) -> Any:
    provider = billing.provider_for(ctx.services.settings, ctx.transport)
    if provider is None or provider.name != order.provider:
        raise ApiError(
            409, "provider_unavailable", "Siparişin ödeme sağlayıcısı şu anda bağlı değil"
        )
    return provider


async def run_refund(ctx: Ctx, payload: dict[str, Any]) -> dict[str, Any]:
    order = await _order(ctx.db, int(payload["order"]))
    provider = _provider(ctx, order)
    ref = await billing.refund_order(ctx.db, provider, order, ctx.services.clock())
    await audit.record(
        ctx.db, "billing.refunded", actor_type="admin", actor_id=str(ctx.actor),
        target_type="order", target_id=str(order.id), ip=ctx.ip,
        details=ctx.details({"amount_minor": order.amount_minor, "currency": order.currency, "refund_ref": ref}),
    )  # fmt: skip
    return {"order": order.id, "status": order.status, "refund_ref": ref}


async def run_review(ctx: Ctx, payload: dict[str, Any]) -> dict[str, Any]:
    order = await _order(ctx.db, int(payload["order"]))
    if order.status != "review":
        raise ApiError(409, "not_in_review", "Sipariş incelemede değil")
    decision, note = str(payload["action"]), str(payload["note"])
    now = ctx.services.clock()
    if decision == "approve":
        order.status = "paid"
        order.paid_at = now
        order.note = f"{order.note or ''} | Onaylandı: {note}".strip(" |")
        await ctx.db.flush()
        await billing.grant_subscription(
            ctx.db, user_id=order.user_id, plan=order.plan_code,
            days=billing.PERIOD_DAYS[order.period], source="payment", now=now, order_id=order.id,
        )  # fmt: skip
    else:
        provider = _provider(ctx, order)
        if not order.provider_payment_id:
            raise ApiError(409, "provider_unavailable", "Siparişin ödeme kimliği yok")
        try:
            ref = await provider.refund(
                provider_payment_id=order.provider_payment_id, amount_minor=order.amount_minor,
                currency=order.currency, order_ref=str(order.public_id),
            )  # fmt: skip
        except ProviderError as exc:
            raise ApiError(502, "provider_error", str(exc)) from exc
        order.status = "refunded"
        order.paid_at = order.paid_at or now
        order.refunded_at = now
        order.refund_ref = ref
        order.note = f"{order.note or ''} | İade: {note}".strip(" |")
    await audit.record(
        ctx.db, f"billing.review_{decision}", actor_type="admin", actor_id=str(ctx.actor),
        target_type="order", target_id=str(order.id), ip=ctx.ip, details=ctx.details({"note": note}),
    )  # fmt: skip
    return {"order": order.id, "status": order.status}


async def check_roles_target(db: AsyncSession, user_id: uuid.UUID, wanted: set[str]) -> User:
    unknown = wanted - set(rbac.ROLES)
    if unknown:
        raise ApiError(422, "unknown_role", "Bilinmeyen rol: " + ", ".join(sorted(unknown)))
    user = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise ApiError(404, "not_found", "Kullanıcı bulunamadı")
    if user.status != "active":
        raise ApiError(409, "invalid_state", "Yalnızca aktif hesaba rol atanabilir")
    if wanted and user.mfa_enabled_at is None:
        raise ApiError(
            409, "mfa_required", "Rol atanmadan önce kullanıcı iki adımlı doğrulamayı açmalı"
        )
    return user


async def run_roles(ctx: Ctx, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = uuid.UUID(str(payload["user"]))
    if user_id == ctx.actor:
        raise ApiError(409, "self_action", "Kendi rollerinizi değiştiremezsiniz")
    wanted = set(payload["roles"])
    user = await check_roles_target(ctx.db, user_id, wanted)
    current = set(await roles_of(ctx.db, user.id))
    added, removed = wanted - current, current - wanted
    try:
        if removed:
            await ctx.db.execute(
                delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_code.in_(removed))
            )
        for code in sorted(added):
            ctx.db.add(UserRole(user_id=user.id, role_code=code, granted_by=ctx.actor))
        await ctx.db.flush()
    except DBAPIError as exc:
        if "SUPER_ADMIN" in str(exc.orig):
            raise ApiError(409, "last_super_admin", "Son SUPER_ADMIN rolü kaldırılamaz") from exc
        raise
    if added or removed:
        # Yetkiler değişti: hedefin açık yönetici oturumları kapatılır.
        await revoke_sessions(ctx.db, ctx.services, user.id, scope="admin")
        await audit.record(
            ctx.db, "admin.roles_changed", actor_type="admin", actor_id=str(ctx.actor),
            target_type="user", target_id=str(user.id), ip=ctx.ip,
            details=ctx.details({"added": sorted(added), "removed": sorted(removed)}),
        )  # fmt: skip
    return {
        "user": str(user.id),
        "roles": sorted(wanted),
        "added": sorted(added),
        "removed": sorted(removed),
    }


async def run_dual_off(ctx: Ctx, payload: dict[str, Any]) -> dict[str, Any]:
    flag = await ctx.db.get(FeatureFlag, "dual_control", with_for_update=True)
    if flag is None:
        raise ApiError(404, "not_found", "Bilinmeyen bayrak")
    before = flag.enabled
    flag.enabled = False
    flag.updated_at = ctx.services.clock()
    flag.updated_by = ctx.actor
    await audit.record(
        ctx.db, "admin.flag_changed", actor_type="admin", actor_id=str(ctx.actor),
        target_type="flag", target_id="dual_control", ip=ctx.ip,
        details=ctx.details({"from": before, "to": False}),
    )  # fmt: skip
    return {"flag": "dual_control", "enabled": False}


ACTIONS: dict[str, Action] = {
    "billing.refund": Action("finance.refund", "Sipariş iadesi", run_refund),
    "billing.review": Action("finance.refund", "İncelemedeki sipariş kararı", run_review),
    "roles.set": Action("roles.assign", "Yönetici rolü değişikliği", run_roles),
    "flags.dual_control_off": Action("flags.manage", "Dört göz kuralını kapatma", run_dual_off),
}


# --- Akış ---------------------------------------------------------------------------------------


async def dual_control_on(db: AsyncSession) -> bool:
    flag = await db.get(FeatureFlag, "dual_control")
    return bool(flag and flag.enabled)


async def submit(
    ctx: Ctx,
    admin: Principal,
    action: str,
    *,
    target: str,
    summary: str,
    payload: dict[str, Any],
    force_approval: bool = False,
) -> dict[str, Any] | Pending:
    """Kural kapalıysa hemen yürütür (sonucu döndürür); açıksa onay talebi açar (``Pending``)."""
    spec = ACTIONS[action]
    if not force_approval and not await dual_control_on(ctx.db):
        return await spec.run(ctx, payload)
    db, now = ctx.db, ctx.services.clock()
    await expire_stale(db, now)
    open_one = (
        await db.execute(
            select(ApprovalRequest.id).where(
                ApprovalRequest.action == action, ApprovalRequest.target == target,
                ApprovalRequest.status == "pending",
            )
        )
    ).scalar_one_or_none()  # fmt: skip
    if open_one is not None:
        raise ApiError(
            409, "approval_pending", f"Bu işlem için bekleyen onay talebi var (#{open_one})"
        )
    req = ApprovalRequest(
        action=action, permission=spec.permission, target=target, summary=summary[:300],
        payload=payload, requested_by=admin.user.id, requested_at=now, expires_at=now + TTL,
    )  # fmt: skip
    try:
        async with db.begin_nested():
            db.add(req)
            await db.flush()
    except IntegrityError as exc:
        raise ApiError(409, "approval_pending", "Bu işlem için bekleyen onay talebi var") from exc
    await audit.record(
        db, "approval.requested", actor_type="admin", actor_id=admin.actor_id,
        target_type="approval", target_id=str(req.id), ip=ctx.ip,
        details={"action": action, "target": target, "summary": req.summary},
    )  # fmt: skip
    return Pending(req.id, req.expires_at)


async def expire_stale(db: AsyncSession, now: datetime) -> int:
    rows = await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= now)
        .values(status="expired", decided_at=now)
        .returning(ApprovalRequest.id)
    )
    return len(rows.all())


async def _load(db: AsyncSession, approval_id: int) -> ApprovalRequest:
    req = await db.get(ApprovalRequest, approval_id, with_for_update=True)
    if req is None:
        raise ApiError(404, "not_found", "Onay talebi bulunamadı")
    if req.status != "pending":
        raise ApiError(409, "approval_closed", "Talep zaten karara bağlanmış")
    return req


def _check_approver(admin: Principal, req: ApprovalRequest) -> None:
    if admin.user.id == req.requested_by:
        raise ApiError(
            409,
            "four_eyes",
            "Kendi talebinizi onaylayamaz ya da reddedemezsiniz; başka bir yönetici gerekli",
        )
    if req.permission not in admin.permissions:
        raise forbidden()


async def approve(
    ctx: Ctx, admin: Principal, approval_id: int, note: str | None
) -> ApprovalRequest:
    db, now = ctx.db, ctx.services.clock()
    req = await _load(db, approval_id)
    _check_approver(admin, req)
    if req.permission in rbac.SENSITIVE and not reauth_fresh(ctx.services, admin.session):
        raise ApiError(
            403, "reauth_required", "Bu işlem için parolanızı ve doğrulama kodunuzu yeniden girin"
        )
    if req.expires_at <= now:
        req.status, req.decided_at = "expired", now
        await db.flush()
        raise ApiError(409, "approval_expired", "Talebin süresi dolmuş", commit=True)
    run = ACTIONS[req.action].run
    exec_ctx = Ctx(db, ctx.services, ctx.transport, admin.user.id, ctx.ip, approval_id=req.id)
    try:
        async with db.begin_nested():
            result = await run(exec_ctx, req.payload)
    except ApiError as exc:
        req.status, req.decided_by, req.decided_at = "failed", admin.user.id, now
        req.decision_note = note
        req.result = {"code": exc.code, "detail": exc.detail}
        await audit.record(
            db, "approval.failed", actor_type="admin", actor_id=admin.actor_id,
            target_type="approval", target_id=str(req.id), ip=ctx.ip,
            details={"action": req.action, "code": exc.code},
        )  # fmt: skip
        await db.flush()
        raise ApiError(
            exc.status, exc.code, f"Onaylandı ancak yürütülemedi: {exc.detail}", commit=True
        ) from exc
    req.status, req.decided_by, req.decided_at = "executed", admin.user.id, now
    req.decision_note, req.result = note, result
    await audit.record(
        db, "approval.executed", actor_type="admin", actor_id=admin.actor_id,
        target_type="approval", target_id=str(req.id), ip=ctx.ip,
        details={"action": req.action, "requested_by": str(req.requested_by)},
    )  # fmt: skip
    await db.flush()
    return req


async def reject(ctx: Ctx, admin: Principal, approval_id: int, note: str) -> ApprovalRequest:
    req = await _load(ctx.db, approval_id)
    _check_approver(admin, req)
    req.status, req.decided_by, req.decided_at = "rejected", admin.user.id, ctx.services.clock()
    req.decision_note = note
    await audit.record(
        ctx.db, "approval.rejected", actor_type="admin", actor_id=admin.actor_id,
        target_type="approval", target_id=str(req.id), ip=ctx.ip,
        details={"action": req.action, "note": note},
    )  # fmt: skip
    await ctx.db.flush()
    return req


async def cancel(ctx: Ctx, admin: Principal, approval_id: int) -> ApprovalRequest:
    req = await _load(ctx.db, approval_id)
    if req.requested_by != admin.user.id:
        raise ApiError(403, "forbidden", "Talebi yalnızca açan yönetici iptal edebilir")
    req.status, req.decided_by, req.decided_at = "cancelled", admin.user.id, ctx.services.clock()
    await audit.record(
        ctx.db, "approval.cancelled", actor_type="admin", actor_id=admin.actor_id,
        target_type="approval", target_id=str(req.id), ip=ctx.ip, details={"action": req.action},
    )  # fmt: skip
    await ctx.db.flush()
    return req


def view(req: ApprovalRequest, emails: dict[uuid.UUID, str], admin: Principal) -> dict[str, Any]:
    spec = ACTIONS.get(req.action)
    return {
        "id": req.id,
        "action": req.action,
        "label": spec.label if spec else req.action,
        "permission": req.permission,
        "target": req.target,
        "summary": req.summary,
        "status": req.status,
        "requested_by": emails.get(req.requested_by),
        "requested_at": req.requested_at.isoformat(),
        "expires_at": req.expires_at.isoformat(),
        "decided_by": emails.get(req.decided_by) if req.decided_by else None,
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
        "decision_note": req.decision_note,
        "result": req.result,
        "mine": req.requested_by == admin.user.id,
        "can_decide": req.status == "pending"
        and req.requested_by != admin.user.id
        and req.permission in admin.permissions,
    }


__all__ = ["ACTIONS", "Ctx", "Pending", "approve", "cancel", "reject", "submit", "view"]
