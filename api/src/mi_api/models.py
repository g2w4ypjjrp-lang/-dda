"""Faz 1 veritabanı modelleri: kimlik, oturum, MFA, RBAC, denetim kaydı, e-posta kuyruğu.

Şema kaynağı Alembic geçişleridir (``migrations/versions``). Bu modeller geçişlerle birebir
eşleşir; ``tests/test_schema.py`` iki tarafın uyumunu doğrular. Veritabanı düzeyindeki
güvenceler (CHECK kısıtları, denetim zinciri tetikleyicisi) geçişlerde tanımlıdır.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="active")
    locale: Mapped[str] = mapped_column(String(8), default="tr")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Istanbul")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_last_counter: Mapped[int | None] = mapped_column(BigInteger)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_digest: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    scope: Mapped[str] = mapped_column(String(8))  # app | admin
    state: Mapped[str] = mapped_column(String(16))  # mfa_pending | active
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reauth_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_attempts: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(24))  # email_verification | password_reset
    token_digest: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_digest: Mapped[bytes] = mapped_column(LargeBinary)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(Text)


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_code: Mapped[str] = mapped_column(
        ForeignKey("roles.code", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_code: Mapped[str] = mapped_column(ForeignKey("roles.code"), primary_key=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    to_address: Mapped[str] = mapped_column(String(320))
    template: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
