# ruff: noqa: E501
"""Yönetim operasyonları API'si (Faz 9).

* ``GET /admin/v1/overview`` — Command Center (bölümler okuma izinlerine göre)
* ``GET /admin/v1/health`` — System Health (``system.read``); ``GET /admin/v1/health/errors`` son 5xx'ler (``logs.read``)
* ``GET /admin/v1/actions`` — Action Center; ``POST /admin/v1/actions/ack`` "görüldü"
* ``POST /admin/v1/billing/orders/{no}/resolve`` — incelemedeki siparişi onayla (abonelik ver) veya iade et
* ``GET/PUT /admin/v1/flags`` — özellik bayrakları (``flags.manage`` hassas); ``GET /v1/notice`` site duyurusu
* ``GET /admin/v1/security`` — Güvenlik Merkezi (``security.read``)
* ``GET /admin/v1/settings`` — gizli olmayan sistem ayarları (``settings.read``)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mi_api import audit, rbac
from mi_api.billing import service as billing
from mi_api.billing.api import order_view
from mi_api.billing.models import Order
from mi_api.billing.providers import ProviderError
from mi_api.context import AdminDep, DbDep, MetaDep, Principal, ServicesDep, require_permission
from mi_api.coupons.models import Coupon
from mi_api.errors import ApiError
from mi_api.football.models import Fixture, Team
from mi_api.models import AuditLog, User, UserRole, UserSession
from mi_api.ops import actions, explorer, health, overview
from mi_api.ops.models import ActionAck, FeatureFlag, SavedFilter

SECURITY_ACTIONS = (
    "auth.login_failed",
    "auth.mfa_failed",
    "admin.login_failed",
    "admin.reauth_failed",
    "auth.password_reset_requested",
    "auth.password_changed",
    "auth.mfa_disabled",
    "admin.roles_changed",
    "admin.user_suspended",
    "billing.license_redeem_failed",
    "billing.webhook_invalid_signature",
)


def _perm(code: str) -> Any:
    return Depends(require_permission(code))


class AckBody(BaseModel):
    key: str = Field(min_length=3, max_length=120)
    note: str | None = Field(default=None, max_length=300)


class ResolveBody(BaseModel):
    action: Literal["approve", "refund"]
    note: str = Field(min_length=5, max_length=300)
    confirm: Literal[True]


class SavedFilterBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    params: dict[str, str] = Field(max_length=20)


class FlagBody(BaseModel):
    enabled: bool
    message: str | None = Field(default=None, max_length=300)


def create_ops_router() -> APIRouter:
    router = APIRouter(tags=["ops"])

    @router.get("/admin/v1/overview")
    async def get_overview(admin: AdminDep, db: DbDep, services: ServicesDep) -> dict[str, Any]:
        now = services.clock()
        out: dict[str, Any] = {"generated_at": now.isoformat()}
        for name, (perm, fn) in overview.SECTIONS.items():
            if perm in admin.permissions:
                out[name] = await fn(db, now)
        return out

    @router.get("/admin/v1/health")
    async def get_health(
        request: Request, db: DbDep, services: ServicesDep, _: Principal = _perm("system.read")
    ) -> dict[str, Any]:
        return await health.snapshot(
            db,
            services.settings,
            request.app.state.redis,
            request.app.state.metrics,
            services.clock(),
        )

    @router.get("/admin/v1/health/errors")
    async def recent_errors(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        _: Principal = _perm("logs.read"),
    ) -> dict[str, Any]:
        return {"items": await request.app.state.metrics.errors(limit)}

    @router.get("/admin/v1/actions")
    async def list_actions(
        request: Request,
        admin: AdminDep,
        db: DbDep,
        services: ServicesDep,
        include_acked: bool = False,
    ) -> dict[str, Any]:
        issues = await actions.collect(
            db,
            services.settings,
            request.app.state.redis,
            request.app.state.metrics,
            services.clock(),
        )
        items = await actions.visible(db, issues, admin.permissions, include_acked)
        counts: dict[str, int] = {}
        for i in items:
            if not i["acked"]:
                counts[i["severity"]] = counts.get(i["severity"], 0) + 1
        return {"items": items, "counts": counts}

    @router.post("/admin/v1/actions/ack")
    async def ack(
        body: AckBody,
        request: Request,
        admin: AdminDep,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
    ) -> dict[str, Any]:
        issues = await actions.collect(
            db,
            services.settings,
            request.app.state.redis,
            request.app.state.metrics,
            services.clock(),
        )
        issue = next((i for i in issues if i.key == body.key), None)
        if issue is None or issue.permission not in admin.permissions:
            raise ApiError(404, "not_found", "Uyarı bulunamadı veya artık geçerli değil")
        if await db.get(ActionAck, body.key) is None:
            db.add(
                ActionAck(
                    issue_key=body.key,
                    acked_by=admin.user.id,
                    acked_at=services.clock(),
                    note=body.note,
                )
            )
        await audit.record(
            db,
            "admin.action_acked",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="issue",
            target_id=body.key,
            ip=meta.ip,
            details={"note": body.note},
        )
        return {"key": body.key, "acked": True}

    @router.post("/admin/v1/billing/orders/{number}/resolve")
    async def resolve_order(
        number: int,
        body: ResolveBody,
        request: Request,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("finance.refund"),
    ) -> dict[str, Any]:
        """İncelemedeki sipariş: tutar doğrulandıysa onayla (abonelik ver) ya da ödemeyi iade et."""
        order = await db.get(Order, number, with_for_update=True)
        if order is None:
            raise ApiError(404, "not_found", "Sipariş bulunamadı")
        if order.status != "review":
            raise ApiError(409, "not_in_review", "Sipariş incelemede değil")
        now = services.clock()
        if body.action == "approve":
            order.status = "paid"
            order.paid_at = now
            order.note = f"{order.note or ''} | Onaylandı: {body.note}".strip(" |")
            await db.flush()
            await billing.grant_subscription(
                db,
                user_id=order.user_id,
                plan=order.plan_code,
                days=billing.PERIOD_DAYS[order.period],
                source="payment",
                now=now,
                order_id=order.id,
            )
        else:
            provider = billing.provider_for(services.settings, request.app.state.payment_transport)
            if provider is None or provider.name != order.provider or not order.provider_payment_id:
                raise ApiError(
                    409,
                    "provider_unavailable",
                    "Siparişin ödeme sağlayıcısı bağlı değil veya ödeme kimliği yok",
                )
            try:
                ref = await provider.refund(
                    provider_payment_id=order.provider_payment_id,
                    amount_minor=order.amount_minor,
                    currency=order.currency,
                    order_ref=str(order.public_id),
                )
            except ProviderError as exc:
                raise ApiError(502, "provider_error", str(exc)) from exc
            order.status = "refunded"
            order.paid_at = order.paid_at or now
            order.refunded_at = now
            order.refund_ref = ref
            order.note = f"{order.note or ''} | İade: {body.note}".strip(" |")
        await audit.record(
            db,
            f"billing.review_{body.action}",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="order",
            target_id=str(order.id),
            ip=meta.ip,
            details={"note": body.note},
        )
        return order_view(order)

    @router.get("/v1/notice")
    async def site_notice(db: DbDep) -> dict[str, Any]:
        flag = await db.get(FeatureFlag, "maintenance_notice")
        return {"message": flag.message if flag and flag.enabled and flag.message else None}

    @router.get("/admin/v1/flags")
    async def list_flags(db: DbDep, _: AdminDep) -> dict[str, Any]:
        rows = (await db.execute(select(FeatureFlag).order_by(FeatureFlag.key))).scalars()
        return {
            "items": [
                {
                    "key": f.key,
                    "enabled": f.enabled,
                    "description": f.description,
                    "message": f.message,
                    "updated_at": f.updated_at.isoformat(),
                }
                for f in rows
            ]
        }

    @router.put("/admin/v1/flags/{key}")
    async def set_flag(
        key: str,
        body: FlagBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("flags.manage"),
    ) -> dict[str, Any]:
        flag = await db.get(FeatureFlag, key, with_for_update=True)
        if flag is None:
            raise ApiError(404, "not_found", "Bilinmeyen bayrak")
        if key == "maintenance_notice" and body.enabled and not (body.message or "").strip():
            raise ApiError(422, "message_required", "Duyuru şeridi için mesaj gerekli")
        before = flag.enabled
        flag.enabled = body.enabled
        flag.message = (body.message or "").strip() or None
        flag.updated_at = services.clock()
        flag.updated_by = admin.user.id
        await audit.record(
            db,
            "admin.flag_changed",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="flag",
            target_id=key,
            ip=meta.ip,
            details={"from": before, "to": body.enabled},
        )
        return {"key": key, "enabled": flag.enabled, "message": flag.message}

    @router.get("/admin/v1/security")
    async def security_center(
        db: DbDep, services: ServicesDep, _: Principal = _perm("security.read")
    ) -> dict[str, Any]:
        now = services.clock()
        since = now - timedelta(hours=24)
        counts = dict(
            (
                await db.execute(
                    select(AuditLog.action, func.count())
                    .where(AuditLog.occurred_at >= since, AuditLog.action.in_(SECURITY_ACTIONS))
                    .group_by(AuditLog.action)
                )
            ).all()
        )
        ips = (
            await db.execute(
                select(func.host(AuditLog.ip), func.count())
                .where(
                    AuditLog.occurred_at >= since,
                    AuditLog.action.in_(
                        ("auth.login_failed", "auth.mfa_failed", "admin.login_failed")
                    ),
                    AuditLog.ip.is_not(None),
                )
                .group_by(func.host(AuditLog.ip))
                .having(func.count() >= 3)
                .order_by(func.count().desc())
                .limit(20)
            )
        ).all()
        staff = (
            await db.execute(
                select(User.email, User.mfa_enabled_at, func.array_agg(UserRole.role_code))
                .join(UserRole, UserRole.user_id == User.id)
                .group_by(User.id)
            )
        ).all()
        sessions = (
            await db.execute(
                select(UserSession, User.email)
                .join(User, User.id == UserSession.user_id)
                .where(
                    UserSession.scope == "admin",
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                    UserSession.state == "active",
                )
                .order_by(UserSession.last_seen_at.desc())
                .limit(50)
            )
        ).all()
        events = (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.action.in_(SECURITY_ACTIONS))
                .order_by(AuditLog.id.desc())
                .limit(50)
            )
        ).scalars()
        return {
            "window_hours": 24,
            "counts": counts,
            "suspicious_ips": [{"ip": ip, "failures": n} for ip, n in ips],
            "staff": {
                "total": len(staff),
                "mfa_enabled": sum(1 for _, mfa, _ in staff if mfa),
                "items": [{"email": e, "mfa": bool(m), "roles": sorted(r)} for e, m, r in staff],
            },
            "admin_sessions": [
                {
                    "email": e,
                    "ip": str(s.ip) if s.ip else None,
                    "last_seen_at": s.last_seen_at.isoformat(),
                    "created_at": s.created_at.isoformat(),
                    "user_agent": s.user_agent,
                }
                for s, e in sessions
            ],
            "events": [
                {
                    "id": a.id,
                    "at": a.occurred_at.isoformat(),
                    "action": a.action,
                    "actor_type": a.actor_type,
                    "ip": str(a.ip) if a.ip else None,
                }
                for a in events
            ],
            "protections": [
                "Argon2id parola özeti; parolalar hiçbir ekranda gösterilmez",
                "Yönetici hesaplarında zorunlu MFA; hassas işlemlerde 5 dk içinde yeniden doğrulama",
                "IP ve hesap bazlı hız sınırları (giriş, kayıt, lisans, ödeme)",
                "Hash zincirli, değiştirilemez denetim kaydı",
                "İmzalı ve tekrar korumalı ödeme bildirimleri",
            ],
        }

    # --- Data Explorer ---------------------------------------------------------------------

    def _explorer_args(request: Request) -> tuple[str | None, dict[str, str], str | None, bool]:
        qp = request.query_params
        filters = {k[2:]: v for k, v in qp.items() if k.startswith("f.") and v != ""}
        return qp.get("q"), filters, qp.get("sort"), qp.get("dir", "desc") != "asc"

    @router.get("/admin/v1/explorer")
    async def explorer_entities(admin: AdminDep) -> dict[str, Any]:
        if "data.explore" not in admin.permissions:
            raise ApiError(403, "forbidden", "Data Explorer yetkiniz yok")
        return {
            "items": [
                explorer.describe(e)
                for e in explorer.ENTITIES.values()
                if e.permission in admin.permissions
            ],
            "can_export": "data.export" in admin.permissions,
        }

    @router.get("/admin/v1/explorer/{entity}")
    async def explorer_rows(
        entity: str,
        request: Request,
        admin: AdminDep,
        db: DbDep,
        page: int = Query(default=1, ge=1, le=10_000),
        page_size: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        e = explorer.entity_for(entity, admin.permissions)
        q, filters, sort, desc = _explorer_args(request)
        stmt = explorer.build(e, q=q, filters=filters, sort=sort, desc=desc)
        total = (
            await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
        rows = (await db.execute(stmt.limit(page_size).offset((page - 1) * page_size))).all()
        return {
            "entity": explorer.describe(e),
            "total": total,
            "page": page,
            "page_size": page_size,
            "rows": [
                {c.key: explorer.jsonable(v) for c, v in zip(e.columns, r, strict=True)}
                for r in rows
            ],
        }

    @router.get("/admin/v1/explorer/{entity}/export.csv", response_model=None)
    async def explorer_export(
        entity: str,
        request: Request,
        db: DbDep,
        meta: MetaDep,
        admin: Principal = _perm("data.export"),
    ) -> Response:
        e = explorer.entity_for(entity, admin.permissions)
        q, filters, sort, desc = _explorer_args(request)
        stmt = explorer.build(e, q=q, filters=filters, sort=sort, desc=desc)
        rows = (await db.execute(stmt.limit(explorer.MAX_EXPORT + 1))).all()
        if len(rows) > explorer.MAX_EXPORT:
            raise ApiError(
                422,
                "too_many_rows",
                f"En fazla {explorer.MAX_EXPORT} satır dışa aktarılabilir; filtreyi daraltın",
            )
        await audit.record(
            db,
            "admin.data_exported",
            actor_type="admin",
            actor_id=admin.actor_id,
            target_type="entity",
            target_id=e.key,
            ip=meta.ip,
            details={"rows": len(rows), "q": q, "filters": filters},
        )
        return Response(
            content=explorer.to_csv(e, list(rows)),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{e.key}.csv"'},
        )

    @router.get("/admin/v1/explorer/{entity}/filters")
    async def saved_filters(entity: str, admin: AdminDep, db: DbDep) -> dict[str, Any]:
        explorer.entity_for(entity, admin.permissions)
        rows = (
            await db.execute(
                select(SavedFilter)
                .where(SavedFilter.user_id == admin.user.id, SavedFilter.entity == entity)
                .order_by(SavedFilter.name)
            )
        ).scalars()
        return {"items": [{"id": f.id, "name": f.name, "params": f.params} for f in rows]}

    @router.post("/admin/v1/explorer/{entity}/filters", status_code=201)
    async def save_filter(
        entity: str, body: SavedFilterBody, admin: AdminDep, db: DbDep, services: ServicesDep
    ) -> dict[str, Any]:
        e = explorer.entity_for(entity, admin.permissions)
        allowed = {"q", "sort", "dir"} | {f"f.{c.key}" for c in e.columns if c.filter}
        if set(body.params) - allowed:
            raise ApiError(422, "invalid_filter", "Kayıtlı filtrede geçersiz alan")
        exists = (
            await db.execute(
                select(SavedFilter).where(
                    SavedFilter.user_id == admin.user.id,
                    SavedFilter.entity == entity,
                    SavedFilter.name == body.name,
                )
            )
        ).scalar_one_or_none()
        if exists:
            exists.params = body.params
            return {"id": exists.id, "name": exists.name, "params": exists.params}
        f = SavedFilter(
            user_id=admin.user.id,
            entity=entity,
            name=body.name,
            params=body.params,
            created_at=services.clock(),
        )
        db.add(f)
        await db.flush()
        return {"id": f.id, "name": f.name, "params": f.params}

    @router.delete("/admin/v1/explorer/filters/{filter_id}")
    async def delete_filter(filter_id: int, admin: AdminDep, db: DbDep) -> dict[str, Any]:
        f = await db.get(SavedFilter, filter_id)
        if f is None or f.user_id != admin.user.id:
            raise ApiError(404, "not_found", "Filtre bulunamadı")
        await db.delete(f)
        return {"deleted": filter_id}

    @router.get("/admin/v1/search")
    async def global_search(
        admin: AdminDep, db: DbDep, q: str = Query(min_length=2, max_length=100)
    ) -> dict[str, Any]:
        """Komut paleti (Ctrl+K) için hızlı arama: yalnızca yetkili varlıklarda, varlık başına 5 sonuç."""
        term = q.strip()
        p = admin.permissions
        out: list[dict[str, Any]] = []
        if "users.read" in p:
            for u in (
                await db.execute(
                    select(User)
                    .where(func.lower(User.email).contains(term.lower(), autoescape=True))
                    .limit(5)
                )
            ).scalars():
                out.append(
                    {
                        "type": "user",
                        "id": str(u.id),
                        "label": u.email,
                        "hint": u.display_name,
                        "href": f"/yonetim/kullanicilar?q={u.email}",
                    }
                )
        if "football.read" in p:
            for t in (
                await db.execute(
                    select(Team)
                    .where(func.lower(Team.name).contains(term.lower(), autoescape=True))
                    .limit(5)
                )
            ).scalars():
                out.append(
                    {
                        "type": "team",
                        "id": str(t.id),
                        "label": t.name,
                        "hint": "Takım",
                        "href": f"/yonetim/veri-gezgini?e=fixtures&f.home_team_id={t.id}",
                    }
                )
        if term.isdigit():
            n = int(term)
            if "finance.read" in p and (await db.get(Order, n)) is not None:
                out.append(
                    {
                        "type": "order",
                        "id": term,
                        "label": f"Sipariş #{n}",
                        "hint": "Sipariş",
                        "href": f"/yonetim/veri-gezgini?e=orders&f.id={n}",
                    }
                )
            if "football.read" in p and (await db.get(Fixture, n)) is not None:
                out.append(
                    {
                        "type": "fixture",
                        "id": term,
                        "label": f"Maç #{n}",
                        "hint": "Maç detayı",
                        "href": f"/maclar/{n}",
                    }
                )
            if "coupons.read" in p and (await db.get(Coupon, n)) is not None:
                out.append(
                    {
                        "type": "coupon",
                        "id": term,
                        "label": f"Kupon #{n}",
                        "hint": "Kupon",
                        "href": f"/yonetim/veri-gezgini?e=coupons&f.id={n}",
                    }
                )
        return {"items": out}

    @router.get("/admin/v1/settings")
    async def system_settings(
        services: ServicesDep, _: Principal = _perm("settings.read")
    ) -> dict[str, Any]:
        s = services.settings
        return {
            "environment": s.environment,
            "football_provider": s.football_provider,
            "payment_provider": s.payment_provider,
            "payments_test_mode": s.payments_test_mode,
            "payments_live_allowed": s.payments_live_allowed,
            "licensing_configured": s.license_pepper is not None,
            "redis_configured": s.redis_url is not None,
            "ml_schedule_enabled": s.ml_schedule_enabled,
            "public_web_url": s.public_web_url,
            "web_origins": list(s.web_origins),
            "admin_origins": list(s.admin_origins),
            "note": "Gizli değerler (anahtar, parola, pepper) hiçbir uçta döndürülmez; değişiklik ortam değişkeniyle yapılır.",
        }

    @router.get("/admin/v1/roles/matrix")
    async def role_matrix(_: Principal = _perm("roles.read")) -> dict[str, Any]:
        return {
            "permissions": [
                {"code": c, "label": label, "sensitive": c in rbac.SENSITIVE}
                for c, label in rbac.PERMISSIONS.items()
            ],
            "roles": [
                {"code": r, "label": rbac.ROLES[r], "permissions": sorted(rbac.ROLE_PERMISSIONS[r])}
                for r in rbac.ROLES
            ],
        }

    return router
