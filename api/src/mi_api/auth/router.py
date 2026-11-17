"""Kullanıcı kimlik doğrulama API'si (``/v1/auth``).

* Kayıt ve parola sıfırlama, e-postanın kayıtlı olup olmadığını açığa vurmaz (aynı yanıt).
* Giriş, var olmayan kullanıcıda da bir Argon2 doğrulaması kadar sürer.
* MFA açık hesapta giriş iki adımlıdır: parola → ``mfa_pending`` oturum (5 dk, 5 deneme) → kod.
* Parola değişince / sıfırlanınca diğer tüm oturumlar kapatılır.
* Hesap silme (KVKK): kişisel alanlar anonimleştirilir, oturumlar kapatılır, denetim kaydı kalır.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr, StringConstraints
from sqlalchemy import delete, func, select, update

from mi_api import audit, rbac
from mi_api.auth.mfa import check_mfa, mfa_aad, require_box
from mi_api.context import (
    APP_COOKIE,
    DbDep,
    MetaDep,
    PendingPrincipal,
    ServicesDep,
    UserDep,
    clear_session_cookie,
    create_session,
    enforce_limit,
    load_session,
    revoke_sessions,
    roles_of,
)
from mi_api.engage import notify
from mi_api.errors import ApiError
from mi_api.models import EmailOutbox, EmailToken, RecoveryCode, User, UserSession
from mi_api.ops import flags
from mi_api.security import (
    hash_password,
    new_recovery_codes,
    new_token,
    new_totp_secret,
    otpauth_uri,
    password_problem,
    recovery_digest,
    token_digest,
    verify_password,
)

VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)
MAX_MFA_ATTEMPTS = 5

Password = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Code = Annotated[str, StringConstraints(min_length=6, max_length=16)]


class RegisterBody(BaseModel):
    email: EmailStr
    password: Password
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    accept_terms: bool


class LoginBody(BaseModel):
    email: EmailStr
    password: Password


class CodeBody(BaseModel):
    code: Code


class TokenBody(BaseModel):
    token: Annotated[str, StringConstraints(min_length=16, max_length=128)]


class EmailBody(BaseModel):
    email: EmailStr


class ResetBody(TokenBody):
    password: Password


class ChangePasswordBody(BaseModel):
    current_password: Password
    new_password: Password


class ReauthBody(BaseModel):
    password: Password
    code: Code | None = None


class MfaDisableBody(BaseModel):
    password: Password
    code: Code


ACCEPTED: dict[str, Any] = {
    "status": "accepted",
    "detail": "İsteğiniz alındı. Hesap varsa e-posta adresinize bilgi gönderildi.",
}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def user_view(user: User, roles: frozenset[str]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "locale": user.locale,
        "timezone": user.timezone,
        "email_verified": user.email_verified_at is not None,
        "mfa_enabled": user.mfa_enabled_at is not None,
        "staff_roles": sorted(roles & rbac.STAFF_ROLES),
        "created_at": user.created_at.isoformat(),
    }


async def _issue_email_token(
    db: DbDep, services: ServicesDep, user: User, purpose: str, ttl: timedelta
) -> str:
    now = services.clock()
    # Aynı amaçlı önceki belirteçler geçersiz kılınır (yalnızca en sonuncusu çalışır).
    await db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token = new_token()
    db.add(
        EmailToken(
            id=uuid.uuid4(),
            user_id=user.id,
            purpose=purpose,
            token_digest=token_digest(token),
            created_at=now,
            expires_at=now + ttl,
        )
    )
    return token


def _outbox(db: DbDep, to: str, template: str, payload: dict[str, Any]) -> None:
    db.add(EmailOutbox(to_address=to, template=template, payload=payload, status="pending"))


async def _consume_token(db: DbDep, services: ServicesDep, token: str, purpose: str) -> User | None:
    now = services.clock()
    row = (
        await db.execute(
            select(EmailToken, User)
            .join(User, User.id == EmailToken.user_id)
            .where(
                EmailToken.token_digest == token_digest(token),
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > now,
                User.status != "deleted",
            )
            .with_for_update(of=EmailToken)
        )
    ).one_or_none()
    if row is None:
        return None
    email_token, user = row
    email_token.used_at = now
    return user


def create_auth_router() -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["auth"])

    @router.post("/register", status_code=202)
    async def register(
        body: RegisterBody, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        await enforce_limit(services, f"register:ip:{meta.ip}", 10, 3600)
        await flags.require(db, "registration_open")
        if not body.accept_terms:
            raise ApiError(422, "terms_required", "Kullanım koşullarını kabul etmeniz gerekiyor")
        email = normalize_email(body.email)
        problem = password_problem(body.password, email)
        if problem:
            raise ApiError(422, "weak_password", problem)
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            # Hesap var: yanıt aynı kalır, sahibine bilgilendirme e-postası gider.
            _outbox(db, email, "account_exists", {"display_name": existing.display_name})
            return ACCEPTED
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=hash_password(body.password),
            display_name=body.display_name,
            status="active",
            password_changed_at=services.clock(),
        )
        db.add(user)
        await db.flush()
        token = await _issue_email_token(db, services, user, "email_verification", VERIFY_TTL)
        link = f"{services.settings.public_web_url}/eposta-dogrula?token={token}"
        _outbox(db, email, "verify_email", {"display_name": user.display_name, "link": link})
        await audit.record(
            db, "user.registered", actor_type="user", actor_id=str(user.id),
            target_type="user", target_id=str(user.id), ip=meta.ip, user_agent=meta.user_agent,
        )  # fmt: skip
        return ACCEPTED

    @router.post("/verify-email")
    async def verify_email(
        body: TokenBody, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, str]:
        await enforce_limit(services, f"verify:ip:{meta.ip}", 30, 3600)
        user = await _consume_token(db, services, body.token, "email_verification")
        if user is None:
            raise ApiError(400, "invalid_token", "Bağlantı geçersiz veya süresi dolmuş")
        if user.email_verified_at is None:
            user.email_verified_at = services.clock()
            await audit.record(
                db, "user.email_verified", actor_type="user", actor_id=str(user.id),
                target_type="user", target_id=str(user.id), ip=meta.ip,
            )  # fmt: skip
        return {"status": "verified"}

    @router.post("/login")
    async def login(
        body: LoginBody, response: Response, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        email = normalize_email(body.email)
        await enforce_limit(services, f"login:ip:{meta.ip}", 30, 600)
        await enforce_limit(services, f"login:email:{email}", 10, 600)
        user = (
            await db.execute(select(User).where(User.email == email, User.status != "deleted"))
        ).scalar_one_or_none()
        if not verify_password(user.password_hash if user else None, body.password) or not user:
            await audit.record(
                db, "auth.login_failed", actor_type="user", actor_id=str(user.id) if user else None,
                target_type="user", target_id=str(user.id) if user else None,
                ip=meta.ip, user_agent=meta.user_agent, details={"scope": "app"},
            )  # fmt: skip
            raise ApiError(401, "invalid_credentials", "E-posta veya parola hatalı", commit=True)
        if user.status == "suspended":
            raise ApiError(
                403, "account_suspended", "Hesabınız askıya alınmış. Destek ile iletişime geçin"
            )
        mfa = user.mfa_enabled_at is not None
        session = await create_session(
            db, services, response, user=user, scope="app",
            state="mfa_pending" if mfa else "active", meta=meta, reauth=not mfa,
        )  # fmt: skip
        if not mfa:
            await audit.record(
                db, "auth.login", actor_type="user", actor_id=str(user.id),
                target_type="session", target_id=str(session.id), ip=meta.ip,
                user_agent=meta.user_agent, details={"scope": "app", "mfa": False},
            )  # fmt: skip
            await notify.login_alert(db, user.id, session.id, meta.ip, services.clock())
            return {
                "status": "ok",
                "mfa_required": False,
                "user": user_view(user, await roles_of(db, user.id)),
            }
        return {"status": "mfa_required", "mfa_required": True}

    @router.post("/login/mfa")
    async def login_mfa(
        body: CodeBody, principal: PendingPrincipal, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        session, user = principal.session, principal.user
        if session.state != "mfa_pending":
            raise ApiError(409, "already_authenticated", "Oturum zaten doğrulanmış")
        session.mfa_attempts += 1
        if session.mfa_attempts > MAX_MFA_ATTEMPTS:
            session.revoked_at = services.clock()
            raise ApiError(
                401, "mfa_locked", "Çok fazla hatalı kod. Yeniden giriş yapın", commit=True
            )
        method = await check_mfa(db, services, user, body.code)
        if method is None:
            await audit.record(
                db, "auth.mfa_failed", actor_type="user", actor_id=str(user.id),
                target_type="session", target_id=str(session.id), ip=meta.ip,
            )  # fmt: skip
            raise ApiError(401, "invalid_code", "Doğrulama kodu hatalı", commit=True)
        now = services.clock()
        session.state = "active"
        session.expires_at = now + timedelta(days=services.settings.session_days)
        session.reauth_at = now
        await audit.record(
            db, "auth.login", actor_type="user", actor_id=str(user.id),
            target_type="session", target_id=str(session.id), ip=meta.ip,
            user_agent=meta.user_agent, details={"scope": "app", "mfa": method},
        )  # fmt: skip
        await notify.login_alert(db, user.id, session.id, meta.ip, services.clock())
        return {"status": "ok", "user": user_view(user, principal.roles)}

    @router.post("/logout")
    async def logout(
        request: Request, response: Response, db: DbDep, services: ServicesDep
    ) -> dict[str, str]:
        loaded = await load_session(db, services, request.cookies.get(APP_COOKIE), "app")
        if loaded is not None:
            user, session = loaded
            session.revoked_at = services.clock()
            await audit.record(
                db, "auth.logout", actor_type="user", actor_id=str(user.id),
                target_type="session", target_id=str(session.id),
            )  # fmt: skip
        clear_session_cookie(response, services, "app")
        return {"status": "ok"}

    @router.get("/me")
    async def me(principal: UserDep) -> dict[str, Any]:
        return user_view(principal.user, principal.roles)

    @router.post("/password/forgot", status_code=202)
    async def forgot(
        body: EmailBody, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        email = normalize_email(body.email)
        await enforce_limit(services, f"forgot:ip:{meta.ip}", 10, 3600)
        await enforce_limit(services, f"forgot:email:{email}", 3, 3600)
        user = (
            await db.execute(select(User).where(User.email == email, User.status == "active"))
        ).scalar_one_or_none()
        if user is not None:
            token = await _issue_email_token(db, services, user, "password_reset", RESET_TTL)
            link = f"{services.settings.public_web_url}/sifre-sifirla?token={token}"
            _outbox(db, email, "password_reset", {"display_name": user.display_name, "link": link})
            await audit.record(
                db, "auth.password_reset_requested", actor_type="user", actor_id=str(user.id),
                target_type="user", target_id=str(user.id), ip=meta.ip,
            )  # fmt: skip
        return ACCEPTED

    @router.post("/password/reset")
    async def reset(
        body: ResetBody, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, str]:
        await enforce_limit(services, f"reset:ip:{meta.ip}", 20, 3600)
        user = await _consume_token(db, services, body.token, "password_reset")
        if user is None or user.status != "active":
            raise ApiError(400, "invalid_token", "Bağlantı geçersiz veya süresi dolmuş")
        problem = password_problem(body.password, user.email)
        if problem:
            raise ApiError(422, "weak_password", problem)
        now = services.clock()
        user.password_hash = hash_password(body.password)
        user.password_changed_at = now
        if user.email_verified_at is None:
            user.email_verified_at = now  # bağlantıyı açan, e-posta kutusunun sahibidir
        await revoke_sessions(db, services, user.id)
        await audit.record(
            db, "auth.password_reset", actor_type="user", actor_id=str(user.id),
            target_type="user", target_id=str(user.id), ip=meta.ip,
        )  # fmt: skip
        await notify.security_event(db, user.id, "auth.password_reset", services.clock())
        return {"status": "ok"}

    @router.post("/password/change")
    async def change_password(
        body: ChangePasswordBody,
        principal: UserDep,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
    ) -> dict[str, str]:
        user = principal.user
        await enforce_limit(services, f"pwchange:user:{user.id}", 5, 600)
        if not verify_password(user.password_hash, body.current_password):
            raise ApiError(401, "invalid_credentials", "Mevcut parola hatalı")
        problem = password_problem(body.new_password, user.email)
        if problem:
            raise ApiError(422, "weak_password", problem)
        user.password_hash = hash_password(body.new_password)
        user.password_changed_at = services.clock()
        await revoke_sessions(db, services, user.id, except_id=principal.session.id)
        await audit.record(
            db, "auth.password_changed", actor_type="user", actor_id=str(user.id),
            target_type="user", target_id=str(user.id), ip=meta.ip,
        )  # fmt: skip
        await notify.security_event(db, user.id, "auth.password_changed", services.clock())
        return {"status": "ok"}

    @router.post("/reauth")
    async def reauth(
        body: ReauthBody, principal: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, str]:
        user = principal.user
        await enforce_limit(services, f"reauth:user:{user.id}", 5, 600)
        if not verify_password(user.password_hash, body.password):
            raise ApiError(401, "invalid_credentials", "Parola hatalı")
        if user.mfa_enabled_at is not None and (
            body.code is None or await check_mfa(db, services, user, body.code) is None
        ):
            raise ApiError(401, "invalid_code", "Doğrulama kodu hatalı")
        principal.session.reauth_at = services.clock()
        await audit.record(
            db, "auth.reauth", actor_type="user", actor_id=str(user.id),
            target_type="session", target_id=str(principal.session.id), ip=meta.ip,
        )  # fmt: skip
        return {"status": "ok"}

    @router.post("/mfa/setup")
    async def mfa_setup(principal: UserDep, db: DbDep, services: ServicesDep) -> dict[str, str]:
        box = require_box(services)
        user = principal.user
        if user.mfa_enabled_at is not None:
            raise ApiError(409, "mfa_already_enabled", "İki adımlı doğrulama zaten açık")
        secret = new_totp_secret()
        user.mfa_secret_enc = box.seal(secret, mfa_aad(user))
        user.mfa_last_counter = None
        return {
            "otpauth_uri": otpauth_uri(secret, user.email),
            "secret": base64.b32encode(secret).decode().rstrip("="),
        }

    @router.post("/mfa/enable")
    async def mfa_enable(
        body: CodeBody, principal: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, Any]:
        require_box(services)
        user = principal.user
        if user.mfa_enabled_at is not None:
            raise ApiError(409, "mfa_already_enabled", "İki adımlı doğrulama zaten açık")
        if user.mfa_secret_enc is None:
            raise ApiError(409, "mfa_setup_required", "Önce kurulumu başlatın")
        await enforce_limit(services, f"mfa_enable:user:{user.id}", 10, 600)
        # Kodu kontrol etmek için geçici olarak etkin kabul edilir; başarısızsa işlem geri alınır.
        user.mfa_enabled_at = services.clock()
        if await check_mfa(db, services, user, body.code) != "totp":
            user.mfa_enabled_at = None
            raise ApiError(401, "invalid_code", "Doğrulama kodu hatalı")
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        codes = new_recovery_codes()
        db.add_all(RecoveryCode(user_id=user.id, code_digest=recovery_digest(c)) for c in codes)
        principal.session.reauth_at = services.clock()
        await audit.record(
            db, "auth.mfa_enabled", actor_type="user", actor_id=str(user.id),
            target_type="user", target_id=str(user.id), ip=meta.ip,
        )  # fmt: skip
        await notify.security_event(db, user.id, "auth.mfa_enabled", services.clock())
        return {"status": "ok", "recovery_codes": codes}

    @router.post("/mfa/disable")
    async def mfa_disable(
        body: MfaDisableBody, principal: UserDep, db: DbDep, services: ServicesDep, meta: MetaDep
    ) -> dict[str, str]:
        user = principal.user
        if user.mfa_enabled_at is None:
            raise ApiError(409, "mfa_not_enabled", "İki adımlı doğrulama kapalı")
        if principal.roles & rbac.STAFF_ROLES:
            raise ApiError(
                403,
                "mfa_required_for_staff",
                "Yönetici hesaplarında iki adımlı doğrulama kapatılamaz",
            )
        await enforce_limit(services, f"mfa_disable:user:{user.id}", 5, 600)
        if not verify_password(user.password_hash, body.password):
            raise ApiError(401, "invalid_credentials", "Parola hatalı")
        if await check_mfa(db, services, user, body.code) is None:
            raise ApiError(401, "invalid_code", "Doğrulama kodu hatalı")
        user.mfa_enabled_at = None
        user.mfa_secret_enc = None
        user.mfa_last_counter = None
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        await audit.record(
            db, "auth.mfa_disabled", actor_type="user", actor_id=str(user.id),
            target_type="user", target_id=str(user.id), ip=meta.ip,
        )  # fmt: skip
        await notify.security_event(db, user.id, "auth.mfa_disabled", services.clock())
        return {"status": "ok"}

    @router.get("/sessions")
    async def sessions(principal: UserDep, db: DbDep, services: ServicesDep) -> dict[str, Any]:
        rows = (
            await db.execute(
                select(UserSession)
                .where(
                    UserSession.user_id == principal.user.id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > services.clock(),
                )
                .order_by(UserSession.last_seen_at.desc())
            )
        ).scalars()
        return {
            "items": [
                {
                    "id": str(s.id),
                    "scope": s.scope,
                    "current": s.id == principal.session.id,
                    "created_at": s.created_at.isoformat(),
                    "last_seen_at": s.last_seen_at.isoformat(),
                    "ip": str(s.ip) if s.ip else None,
                    "user_agent": s.user_agent,
                }
                for s in rows
            ]
        }

    @router.post("/sessions/{session_id}/revoke")
    async def revoke_session(
        session_id: uuid.UUID, principal: UserDep, db: DbDep, services: ServicesDep
    ) -> dict[str, str]:
        result = await db.execute(
            update(UserSession)
            .where(
                UserSession.id == session_id,
                UserSession.user_id == principal.user.id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=services.clock())
        )
        if getattr(result, "rowcount", 0) == 0:
            raise ApiError(404, "not_found", "Oturum bulunamadı")
        await audit.record(
            db, "auth.session_revoked", actor_type="user", actor_id=str(principal.user.id),
            target_type="session", target_id=str(session_id),
        )  # fmt: skip
        return {"status": "ok"}

    @router.post("/delete-account")
    async def delete_account(
        body: ReauthBody,
        response: Response,
        principal: UserDep,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
    ) -> dict[str, str]:
        user = principal.user
        await enforce_limit(services, f"delete:user:{user.id}", 5, 600)
        if not verify_password(user.password_hash, body.password):
            raise ApiError(401, "invalid_credentials", "Parola hatalı")
        if user.mfa_enabled_at is not None and (
            body.code is None or await check_mfa(db, services, user, body.code) is None
        ):
            raise ApiError(401, "invalid_code", "Doğrulama kodu hatalı")
        if principal.roles & rbac.STAFF_ROLES:
            raise ApiError(
                409, "staff_account", "Yönetici hesabı silinmeden önce rolleri kaldırılmalı"
            )
        now: datetime = services.clock()
        await revoke_sessions(db, services, user.id)
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        await db.execute(delete(EmailToken).where(EmailToken.user_id == user.id))
        # E-posta kuyruğundaki bekleyen iletiler de kişisel veri içerir.
        await db.execute(
            update(EmailOutbox)
            .where(EmailOutbox.to_address == user.email, EmailOutbox.status == "pending")
            .values(status="discarded", payload=func.jsonb_build_object())
        )
        user.email = f"deleted-{user.id}@deleted.invalid"
        user.display_name = "Silinmiş kullanıcı"
        user.password_hash = None
        user.mfa_secret_enc = None
        user.mfa_enabled_at = None
        user.mfa_last_counter = None
        user.status = "deleted"
        user.deleted_at = now
        await audit.record(
            db, "user.deleted", actor_type="user", actor_id=str(user.id),
            target_type="user", target_id=str(user.id), ip=meta.ip,
        )  # fmt: skip
        clear_session_cookie(response, services, "app")
        return {"status": "deleted"}

    return router
