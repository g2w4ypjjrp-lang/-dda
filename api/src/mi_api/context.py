"""Uygulama bağımlılıkları ve ortak kimlik doğrulama yardımcıları."""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, Request, Response
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api import rbac
from mi_api.config import Settings
from mi_api.db import Database
from mi_api.errors import ApiError, forbidden, rate_limited, unauthorized
from mi_api.models import User, UserSession
from mi_api.ratelimit import Limiter
from mi_api.security import SecretBox, new_token, token_digest

APP_COOKIE = "mi_session"
ADMIN_COOKIE = "mi_admin"
ADMIN_COOKIE_PATH = "/admin/"
Clock = Callable[[], datetime]
Scope = Literal["app", "admin"]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Services:
    settings: Settings
    db: Database
    limiter: Limiter
    clock: Clock = utcnow
    box: SecretBox | None = field(default=None)

    @classmethod
    def build(cls, settings: Settings, db: Database, limiter: Limiter, clock: Clock) -> Services:
        kek = settings.secret_kek_bytes()
        return cls(settings, db, limiter, clock, SecretBox(kek) if kek else None)


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_db(services: ServicesDep) -> AsyncIterator[AsyncSession]:
    """İstek başına bir işlem: başarıda commit, hatada rollback (``ApiError.commit`` hariç)."""
    async with services.db.sessions() as session:
        try:
            yield session
        except ApiError as exc:
            if exc.commit:
                await session.commit()
            else:
                await session.rollback()
            raise
        except BaseException:
            await session.rollback()
            raise
        else:
            await session.commit()


DbDep = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request, settings: Settings) -> str | None:
    peer = request.client.host if request.client else None
    if peer and peer in settings.trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for", "")
        candidate = forwarded.split(",")[-1].strip() if forwarded else ""
        if candidate:
            peer = candidate
    try:
        return str(ipaddress.ip_address(peer)) if peer else None
    except ValueError:
        return None


@dataclass
class RequestMeta:
    ip: str | None
    user_agent: str | None


def get_meta(request: Request, services: ServicesDep) -> RequestMeta:
    return RequestMeta(client_ip(request, services.settings), request.headers.get("user-agent"))


MetaDep = Annotated[RequestMeta, Depends(get_meta)]


async def enforce_limit(services: Services, key: str, limit: int, window_s: float) -> None:
    if not await services.limiter.allow(key, limit, window_s):
        raise rate_limited()


# --- Oturumlar --------------------------------------------------------------------------------


async def create_session(
    db: AsyncSession,
    services: Services,
    response: Response,
    *,
    user: User,
    scope: Scope,
    state: Literal["mfa_pending", "active"],
    meta: RequestMeta,
    reauth: bool = False,
) -> UserSession:
    now = services.clock()
    cfg = services.settings
    if state == "mfa_pending":
        lifetime = timedelta(seconds=cfg.mfa_pending_s)
    elif scope == "admin":
        lifetime = timedelta(hours=cfg.admin_session_hours)
    else:
        lifetime = timedelta(days=cfg.session_days)
    token = new_token()
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_digest=token_digest(token),
        scope=scope,
        state=state,
        created_at=now,
        expires_at=now + lifetime,
        last_seen_at=now,
        reauth_at=now if reauth else None,
        mfa_attempts=0,
        ip=meta.ip,
        user_agent=(meta.user_agent or "")[:512] or None,
    )
    db.add(session)
    await db.flush()
    set_session_cookie(response, services, scope, token, lifetime)
    return session


def set_session_cookie(
    response: Response, services: Services, scope: Scope, token: str, lifetime: timedelta
) -> None:
    response.set_cookie(
        APP_COOKIE if scope == "app" else ADMIN_COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        path="/" if scope == "app" else ADMIN_COOKIE_PATH,
        secure=services.settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, services: Services, scope: Scope) -> None:
    response.delete_cookie(
        APP_COOKIE if scope == "app" else ADMIN_COOKIE,
        path="/" if scope == "app" else ADMIN_COOKIE_PATH,
        secure=services.settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )


async def load_session(
    db: AsyncSession, services: Services, token: str | None, scope: Scope
) -> tuple[User, UserSession] | None:
    if not token or len(token) > 128:
        return None
    now = services.clock()
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_digest == token_digest(token),
                UserSession.scope == scope,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                User.status == "active",
            )
        )
    ).one_or_none()
    if row is None:
        return None
    session, user = row
    if (now - session.last_seen_at).total_seconds() > 60:
        session.last_seen_at = now
    return user, session


async def revoke_sessions(
    db: AsyncSession,
    services: Services,
    user_id: uuid.UUID,
    *,
    scope: Scope | None = None,
    except_id: uuid.UUID | None = None,
) -> None:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=services.clock())
    )
    if scope is not None:
        stmt = stmt.where(UserSession.scope == scope)
    if except_id is not None:
        stmt = stmt.where(UserSession.id != except_id)
    await db.execute(stmt)


@dataclass
class Principal:
    user: User
    session: UserSession
    roles: frozenset[str] = frozenset()
    permissions: frozenset[str] = frozenset()

    @property
    def actor_id(self) -> str:
        return str(self.user.id)


async def roles_of(db: AsyncSession, user_id: uuid.UUID) -> frozenset[str]:
    result = await db.execute(
        text("SELECT role_code FROM user_roles WHERE user_id = :u"), {"u": user_id}
    )
    return frozenset(str(r) for r in result.scalars())


async def permissions_of(db: AsyncSession, user_id: uuid.UUID) -> frozenset[str]:
    result = await db.execute(
        text("SELECT permission_code FROM user_effective_permissions WHERE user_id = :u"),
        {"u": user_id},
    )
    return frozenset(str(r) for r in result.scalars())


async def _pending_or_active(request: Request, db: DbDep, services: ServicesDep) -> Principal:
    loaded = await load_session(db, services, request.cookies.get(APP_COOKIE), "app")
    if loaded is None:
        raise unauthorized()
    user, session = loaded
    return Principal(user, session, await roles_of(db, user.id))


async def current_user(principal: Annotated[Principal, Depends(_pending_or_active)]) -> Principal:
    if principal.session.state != "active":
        raise ApiError(401, "mfa_required", "Doğrulama kodunu girmeniz gerekiyor")
    return principal


PendingPrincipal = Annotated[Principal, Depends(_pending_or_active)]
UserDep = Annotated[Principal, Depends(current_user)]


async def optional_user(request: Request, db: DbDep, services: ServicesDep) -> Principal | None:
    """Herkese açık uçlar için: oturum varsa (ve MFA tamamsa) kullanıcı, yoksa None."""
    loaded = await load_session(db, services, request.cookies.get(APP_COOKIE), "app")
    if loaded is None or loaded[1].state != "active":
        return None
    return Principal(loaded[0], loaded[1])


OptionalUserDep = Annotated[Principal | None, Depends(optional_user)]


async def current_admin(request: Request, db: DbDep, services: ServicesDep) -> Principal:
    loaded = await load_session(db, services, request.cookies.get(ADMIN_COOKIE), "admin")
    if loaded is None:
        raise unauthorized()
    user, session = loaded
    roles = await roles_of(db, user.id)
    # Rolü alınan veya MFA'sı kapatılan yönetici, oturumu açık olsa bile içeri giremez.
    if not (roles & rbac.STAFF_ROLES) or user.mfa_enabled_at is None:
        raise forbidden()
    return Principal(user, session, roles, await permissions_of(db, user.id))


AdminDep = Annotated[Principal, Depends(current_admin)]


def reauth_fresh(services: Services, session: UserSession) -> bool:
    if session.reauth_at is None:
        return False
    age = (services.clock() - session.reauth_at).total_seconds()
    return 0 <= age <= services.settings.reauth_window_s


def require_permission(code: str) -> Callable[..., Awaitable[Principal]]:
    """Yönetici izni ister; hassas izinlerde son birkaç dakikada yeniden doğrulama da ister."""
    if code not in rbac.PERMISSIONS:
        raise ValueError(f"Bilinmeyen izin: {code}")

    async def dependency(admin: AdminDep, services: ServicesDep) -> Principal:
        if code not in admin.permissions:
            raise forbidden()
        if code in rbac.SENSITIVE and not reauth_fresh(services, admin.session):
            raise ApiError(
                403,
                "reauth_required",
                "Bu işlem için parolanızı ve doğrulama kodunuzu yeniden girin",
            )
        return admin

    return dependency
