"""Faz 8 ORM modelleri (şema: geçiş 0008)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mi_api.models import Base


class DesignVersion(Base):
    __tablename__ = "design_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    design_key: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    based_on: Mapped[int | None] = mapped_column(ForeignKey("design_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class DesignSettings(Base):
    __tablename__ = "design_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    default_design: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
