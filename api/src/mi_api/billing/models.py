"""Faz 6 ORM modelleri (şema: geçiş 0006)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mi_api.models import Base


class Plan(Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    tagline: Mapped[str] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(SmallInteger)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)


class PlanEntitlement(Base):
    __tablename__ = "plan_entitlements"

    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"), primary_key=True)
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlanPrice(Base):
    __tablename__ = "plan_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    period: Mapped[str] = mapped_column(String(8))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="TRY")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    period: Mapped[str] = mapped_column(String(8))
    price_id: Mapped[int] = mapped_column(ForeignKey("plan_prices.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    provider: Mapped[str] = mapped_column(String(16))
    test_mode: Mapped[bool] = mapped_column(Boolean)
    provider_ref: Mapped[str | None] = mapped_column(Text)
    provider_payment_id: Mapped[str | None] = mapped_column(Text)
    consent: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_ref: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class PaymentEventRow(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(16))
    event_id: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signature_valid: Mapped[bool] = mapped_column(Boolean)
    event_type: Mapped[str | None] = mapped_column(String(32))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(24))
    detail: Mapped[str | None] = mapped_column(Text)


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_digest: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    key_hint: Mapped[str] = mapped_column(String(4))
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    duration_days: Mapped[int] = mapped_column(Integer)
    max_activations: Mapped[int] = mapped_column(Integer, default=1)
    activations_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(8), default="active")
    redeem_before: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    status: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(8))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), unique=True)
    license_id: Mapped[int | None] = mapped_column(ForeignKey("licenses.id"))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LicenseActivation(Base):
    __tablename__ = "license_activations"

    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"))


class UsageDaily(Base):
    __tablename__ = "usage_daily"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
