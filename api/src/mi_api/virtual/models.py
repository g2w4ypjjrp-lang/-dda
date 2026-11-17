"""Faz 5 ORM modelleri (şema: geçiş 0005). Bakiye yalnızca defter tetikleyicisiyle değişir."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mi_api.models import Base


class VirtualAccount(Base):
    __tablename__ = "virtual_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    starting_balance_minor: Mapped[int] = mapped_column(BigInteger)
    balance_minor: Mapped[int] = mapped_column(BigInteger)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    pending_settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    pending_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ledger(Base):
    __tablename__ = "virtual_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("virtual_accounts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    balance_minor: Mapped[int] = mapped_column(BigInteger)  # tetikleyici hesaplar
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("virtual_tickets.id"))
    note: Mapped[str | None] = mapped_column(Text)


class Ticket(Base):
    __tablename__ = "virtual_tickets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("virtual_accounts.id"))
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stake_minor: Mapped[int] = mapped_column(BigInteger)
    odds: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    odds_source: Mapped[str] = mapped_column(String(16))
    model_probability: Mapped[float] = mapped_column(Float)
    staking: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(8), default="pending")
    payout_minor: Mapped[int | None] = mapped_column(BigInteger)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
