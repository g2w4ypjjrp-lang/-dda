"""Faz 4 ORM modelleri (şema: geçiş 0004). İçerik değiştirilemez; yalnızca sonuç bir kez yazılır."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mi_api.models import Base


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    profile: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    legs_count: Mapped[int] = mapped_column(SmallInteger)
    joint_probability: Mapped[float] = mapped_column(Float)
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(8), default="pending")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CouponLeg(Base):
    __tablename__ = "coupon_legs"

    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("ml_predictions.id"))
    fixture_id: Mapped[int] = mapped_column(ForeignKey("football_fixtures.id"))
    market: Mapped[str] = mapped_column(String(16))
    pick: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(Text)
    probability: Mapped[float] = mapped_column(Float)
    reliability: Mapped[str] = mapped_column(String(8))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String(8), default="pending")
