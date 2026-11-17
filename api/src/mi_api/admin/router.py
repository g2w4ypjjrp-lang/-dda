"""Yönetim API'si (``/admin/v1``) — Faz 1: yönetici oturumu, kullanıcı yönetimi, roller, denetim.

* Ayrı çerez (``mi_admin``, yalnızca ``/admin/`` yolunda), ayrı köken listesi, en fazla 12 saat.
* Giriş tek adımda parola + MFA kodu ister; MFA'sı olmayan personel giriş yapamaz.
* Her uç nokta ``require_permission`` ile backend'de yetkilendirilir; hassas izinler son
  ``reauth_window_s`` içinde yeniden doğrulama ister.
* Kullanıcı parolaları hiçbir uç noktada döndürülmez (özet dahil).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, StringConstraints
from sqlalchemy import func, or_, select, text

from mi_api import audit, rbac
from mi_api.auth.mfa import check_mfa
from mi_api.auth.router import normalize_email
from mi_api.context import (
    ADMIN_COOKIE,
    AdminDep,
    DbDep,
    MetaDep,
    Principal,
    ServicesDep,
    clear_session_cookie,
    create_session,
    enforce_limit,
    load_session,
    permissions_of,
    reauth_fresh,
    require_permission,
    revoke_sessions,
    roles_of,
)
from mi_api.errors import ApiError, forbidden
from mi_api.models import AuditLog, Permission, Role, RolePermission, User, UserRole, UserSession
from mi_api.ops import approvals
from mi_api.security import verify_password

Password = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Code = Annotated[str, StringConstraints(min_length=6, max_length=16)]


class AdminLoginBody(BaseModel):
    email: EmailStr
    password: Password
    code: Code


class ReauthBody(BaseModel):
    password: Password
    code: Code


class SuspendBody(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class RolesBody(BaseModel):
    roles: list[str] = Field(max_length=len(rbac.ROLES))


def _perm(code: str) -> Any:
    return Depends(require_permission(code))


def admin_view(principal: Principal, services: Any) -> dict[str, Any]:
    return {
        "id": principal.actor_id,
        "email": principal.user.email,
        "display_name": principal.user.display_name,
        "roles": sorted(principal.roles & rbac.STAFF_ROLES),
        "permissions": sorted(principal.permissions),
        "reauth_fresh": reauth_fresh(services, principal.session),
        "session_expires_at": principal.session.expires_at.isoformat(),
    }


def user_row(user: User, roles: list[str]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "email_verified": user.email_verified_at is not None,
        "mfa_enabled": user.mfa_enabled_at is not None,
        "roles": sorted(roles),
        "created_at": user.created_at.isoformat(),
    }


def _audit_row(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "occurred_at": row.occurred_at.isoformat(),
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "ip": str(row.ip) if row.ip else None,
        "details": row.details,
    }


def create_admin_router() -> APIRouter:
    router = APIRouter(prefix="/admin/v1", tags=["admin"])

    # --- Oturum ---------------------------------------------------------------------------------

    @router.post("/auth/login")
    async def admin_login(
        body: AdminLoginBody, response: Response, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        email = normalize_email(body.email)
        await enforce_limit(services, f"admin_login:ip:{meta.ip}", 20, 600)
        await enforce_limit(services, f"admin_login:email:{email}", 5, 600)
        user = (
            await db.execute(select(User).where(User.email == email, User.status == "active"))
        ).scalar_one_or_none()
        password_ok = verify_password(user.password_hash if user else None, body.password)
        roles = await roles_of(db, user.id) if user and password_ok else frozenset()
        staff = bool(roles & rbac.STAFF_ROLES)
        if user is None or not password_ok or not staff:
            await audit.record(
                db, "admin.login_failed", actor_type="admin",
                actor_id=str(user.id) if user else None, ip=meta.ip, user_agent=meta.user_agent,
                details={"reason": "credentials" if not password_ok else "not_staff"},
            )  # fmt: skip
            raise ApiError(401, "invalid_credentials", "Giriş bilgileri hatalı", commit=True)
        if user.mfa_enabled_at is None:
            raise ApiError(
                403,
                "mfa_enrollment_required",
                "Yönetim paneline girmeden önce hesabınızda iki adımlı doğrulamayı açın",
            )
        method = await check_mfa(db, services, user, body.code)
        if method is None:
            await audit.record(
                db, "admin.login_failed", actor_type="admin", actor_id=str(user.id),
                ip=meta.ip, user_agent=meta.user_agent, details={"reason": "mfa"},
            )  # fmt: skip
            raise ApiError(401, "invalid_credentials", "Giriş bilgileri hatalı", commit=True)
        session = await create_session(
            db, services, response, user=user, scope="admin", state="active", meta=meta, reauth=True
        )
        await audit.record(
            db, "admin.login", actor_type="admin", actor_id=str(user.id),
            target_type="session", target_id=str(session.id), ip=meta.ip,
            user_agent=meta.user_agent, details={"mfa": method},
        )  # fmt: skip
        principal = Principal(user, session, roles, await permissions_of(db, user.id))
        return admin_view(principal, services)

    @router.post("/auth/logout")
    async def admin_logout(
        request: Request, response: Response, db: DbDep, services: ServicesDep
    ) -> dict[str, str]:
        loaded = await load_session(db, services, request.cookies.get(ADMIN_COOKIE), "admin")
        if loaded is not None:
            user, session = loaded
            session.revoked_at = services.clock()
            await audit.record(
                db, "admin.logout", actor_type="admin", actor_id=str(user.id),
                target_type="session", target_id=str(session.id),
            )  # fmt: skip
        clear_session_cookie(response, services, "admin")
        return {"status": "ok"}

    @router.post("/auth/reauth")
    async def admin_reauth(
        body: ReauthBody, admin: AdminDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        await enforce_limit(services, f"admin_reauth:user:{admin.user.id}", 5, 600)
        if not verify_password(admin.user.password_hash, body.password) or (
            await check_mfa(db, services, admin.user, body.code) is None
        ):
            await audit.record(
                db, "admin.reauth_failed", actor_type="admin", actor_id=admin.actor_id, ip=meta.ip
            )
            raise ApiError(401, "invalid_credentials", "Parola veya kod hatalı", commit=True)
        admin.session.reauth_at = services.clock()
        await audit.record(
            db, "admin.reauth", actor_type="admin", actor_id=admin.actor_id,
            target_type="session", target_id=str(admin.session.id), ip=meta.ip,
        )  # fmt: skip
        return admin_view(admin, services)

    @router.get("/me")
    async def admin_me(admin: AdminDep, services: ServicesDep) -> dict[str, Any]:
        return admin_view(admin, services)

    # --- Kullanıcılar ---------------------------------------------------------------------------

    @router.get("/users")
    async def list_users(
        db: DbDep,
        _: Principal = _perm("users.read"),
        q: Annotated[str | None, Query(max_length=120)] = None,
        status: Literal["active", "suspended", "deleted"] | None = None,
        role: str | None = None,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> dict[str, Any]:
        stmt = select(User)
        if q:
            pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
        if status:
            stmt = stmt.where(User.status == status)
        if role:
            if role not in rbac.ROLES:
                raise ApiError(422, "unknown_role", "Bilinmeyen rol")
            stmt = stmt.where(
                User.id.in_(select(UserRole.user_id).where(UserRole.role_code == role))
            )
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        users = (
            (
                await db.execute(
                    stmt.order_by(User.created_at.desc(), User.id)
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .scalars()
            .all()
        )
        role_rows = (
            await db.execute(
                select(UserRole.user_id, UserRole.role_code).where(
                    UserRole.user_id.in_([u.id for u in users])
                )
            )
        ).all()
        roles: dict[uuid.UUID, list[str]] = {}
        for uid, code in role_rows:
            roles.setdefault(uid, []).append(code)
        return {
            "items": [user_row(u, roles.get(u.id, [])) for u in users],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def _get_user(db: DbDep, user_id: uuid.UUID) -> User:
        user = (
            await db.execute(select(User).where(User.id == user_id).with_for_update())
        ).scalar_one_or_none()
        if user is None:
            raise ApiError(404, "not_found", "Kullanıcı bulunamadı")
        return user

    @router.get("/users/{user_id}")
    async def get_user(
        user_id: uuid.UUID, db: DbDep, services: ServicesDep, _: Principal = _perm("users.read")
    ) -> dict[str, Any]:
        user = await _get_user(db, user_id)
        roles = await roles_of(db, user.id)
        active_sessions = (
            await db.execute(
                select(UserSession.scope, func.count())
                .where(
                    UserSession.user_id == user.id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > services.clock(),
                )
                .group_by(UserSession.scope)
            )
        ).all()
        activity = (
            await db.execute(
                select(AuditLog)
                .where(
                    or_(
                        (AuditLog.target_type == "user") & (AuditLog.target_id == str(user.id)),
                        AuditLog.actor_id == str(user.id),
                    )
                )
                .order_by(AuditLog.id.desc())
                .limit(50)
            )
        ).scalars()
        return {
            **user_row(user, list(roles)),
            "locale": user.locale,
            "timezone": user.timezone,
            "suspended_reason": user.suspended_reason,
            "active_sessions": dict(active_sessions),
            "activity": [_audit_row(a) for a in activity],
        }

    @router.post("/users/{user_id}/suspend")
    async def suspend_user(
        user_id: uuid.UUID,
        body: SuspendBody,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("users.manage"),
    ) -> dict[str, str]:
        if user_id == admin.user.id:
            raise ApiError(409, "self_action", "Kendi hesabınızı askıya alamazsınız")
        user = await _get_user(db, user_id)
        if user.status != "active":
            raise ApiError(409, "invalid_state", "Yalnızca aktif hesap askıya alınabilir")
        target_roles = await roles_of(db, user.id)
        if "SUPER_ADMIN" in target_roles and "SUPER_ADMIN" not in admin.roles:
            raise forbidden("SUPER_ADMIN hesabını yalnızca bir SUPER_ADMIN askıya alabilir")
        if "SUPER_ADMIN" in target_roles:
            others = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM user_roles ur JOIN users u ON u.id = ur.user_id"
                        " WHERE ur.role_code = 'SUPER_ADMIN' AND u.status = 'active'"
                        " AND u.id <> :u"
                    ),
                    {"u": user.id},
                )
            ).scalar_one()
            if others == 0:
                raise ApiError(409, "last_super_admin", "Son SUPER_ADMIN askıya alınamaz")
        user.status = "suspended"
        user.suspended_reason = body.reason
        await revoke_sessions(db, services, user.id)
        await audit.record(
            db, "admin.user_suspended", actor_type="admin", actor_id=admin.actor_id,
            target_type="user", target_id=str(user.id), ip=meta.ip,
            details={"reason": body.reason},
        )  # fmt: skip
        return {"status": "suspended"}

    @router.post("/users/{user_id}/activate")
    async def activate_user(
        user_id: uuid.UUID,
        db: DbDep,
        meta: MetaDep,
        admin: Principal = _perm("users.manage"),
    ) -> dict[str, str]:
        user = await _get_user(db, user_id)
        if user.status != "suspended":
            raise ApiError(409, "invalid_state", "Yalnızca askıdaki hesap etkinleştirilebilir")
        user.status = "active"
        user.suspended_reason = None
        await audit.record(
            db, "admin.user_activated", actor_type="admin", actor_id=admin.actor_id,
            target_type="user", target_id=str(user.id), ip=meta.ip,
        )  # fmt: skip
        return {"status": "active"}

    # --- Roller -----------------------------------------------------------------------------

    @router.get("/roles")
    async def list_roles(db: DbDep, _: Principal = _perm("roles.read")) -> dict[str, Any]:
        roles = (await db.execute(select(Role).order_by(Role.code))).scalars().all()
        perms = (await db.execute(select(Permission).order_by(Permission.code))).scalars().all()
        pairs = (await db.execute(select(RolePermission))).scalars().all()
        counts = dict(
            (
                await db.execute(
                    select(UserRole.role_code, func.count()).group_by(UserRole.role_code)
                )
            ).all()
        )
        matrix: dict[str, list[str]] = {}
        for pair in pairs:
            matrix.setdefault(pair.role_code, []).append(pair.permission_code)
        return {
            "roles": [
                {
                    "code": r.code,
                    "description": r.description,
                    "permissions": sorted(matrix.get(r.code, [])),
                    "member_count": counts.get(r.code, 0),
                }
                for r in roles
            ],
            "permissions": [
                {"code": p.code, "description": p.description, "sensitive": p.sensitive}
                for p in perms
            ],
        }

    @router.put("/users/{user_id}/roles", response_model=None)
    async def set_roles(
        user_id: uuid.UUID,
        body: RolesBody,
        request: Request,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = _perm("roles.assign"),
    ) -> dict[str, Any] | JSONResponse:
        """Rol değişikliği. Dört göz kuralı açıksa 202 + onay talebi döner (``ops.approvals``)."""
        wanted = set(body.roles)
        if user_id == admin.user.id:
            raise ApiError(409, "self_action", "Kendi rollerinizi değiştiremezsiniz")
        user = await approvals.check_roles_target(db, user_id, wanted)
        current = set(await roles_of(db, user.id))
        if wanted == current:
            return {"roles": sorted(wanted)}
        ctx = approvals.Ctx(
            db, services, request.app.state.payment_transport, admin.user.id, meta.ip
        )
        added, removed = sorted(wanted - current), sorted(current - wanted)
        change = ", ".join([f"+{r}" for r in added] + [f"-{r}" for r in removed])
        done = await approvals.submit(
            ctx, admin, "roles.set", target=f"user:{user.id}",
            summary=f"{user.email} rolleri: {change}",
            payload={"user": str(user.id), "roles": sorted(wanted)},
        )  # fmt: skip
        if isinstance(done, approvals.Pending):
            return JSONResponse(done.body(), status_code=202)
        return {"roles": sorted(wanted)}

    # --- Denetim kaydı ------------------------------------------------------------------------

    @router.get("/audit")
    async def list_audit(
        db: DbDep,
        _: Principal = _perm("audit.read"),
        action: Annotated[str | None, Query(max_length=80)] = None,
        actor_id: Annotated[str | None, Query(max_length=64)] = None,
        target_id: Annotated[str | None, Query(max_length=64)] = None,
        before_id: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        stmt = select(AuditLog)
        if action:
            stmt = stmt.where(AuditLog.action.startswith(action, autoescape=True))
        if actor_id:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if target_id:
            stmt = stmt.where(AuditLog.target_id == target_id)
        if before_id:
            stmt = stmt.where(AuditLog.id < before_id)
        rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit))).scalars().all()
        return {
            "items": [_audit_row(r) for r in rows],
            "next_before_id": rows[-1].id if len(rows) == limit else None,
        }

    @router.get("/audit/verify")
    async def verify_audit(db: DbDep, _: Principal = _perm("audit.read")) -> dict[str, Any]:
        broken = await audit.verify_chain(db)
        count = (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        return {"intact": broken is None, "first_broken_id": broken, "entries": count}

    return router
