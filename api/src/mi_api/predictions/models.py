"""Faz 3 ORM modelleri (şema kaynağı: geçiş 0003). Tahmin satırları değiştirilemez (tetikleyici)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mi_api.models import Base


class ModelVersion(Base):
    __tablename__ = "ml_model_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(64))
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    family: Mapped[str] = mapped_column(String(32), default="ensemble_1x2")
    status: Mapped[str] = mapped_column(String(16), default="challenger")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trained_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seed: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB)
    excluded: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    temperature: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    feature_importance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    data_fingerprint: Mapped[str] = mapped_column(String(64))
    n_rows: Mapped[int] = mapped_column(Integer)
    artifact: Mapped[dict[str, Any]] = mapped_column(JSONB)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class TuningTrial(Base):
    __tablename__ = "ml_tuning_trials"

    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("ml_model_versions.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    value: Mapped[float | None] = mapped_column(Float)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Prediction(Base):
    __tablename__ = "ml_predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("football_fixtures.id"))
    model_version_id: Mapped[int] = mapped_column(ForeignKey("ml_model_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    # none_as_null: Python None → SQL NULL (JSON "null" değil; çekimserlik kısıtı buna bağlı).
    probabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    uncertainty: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reliability: Mapped[str] = mapped_column(String(8))
    data_quality: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model_agreement: Mapped[float | None] = mapped_column(Float)
    abstain_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    feature_hash: Mapped[str] = mapped_column(String(64))
    data_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PredictionOutcome(Base):
    __tablename__ = "ml_prediction_outcomes"

    prediction_id: Mapped[int] = mapped_column(ForeignKey("ml_predictions.id"), primary_key=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    home_goals: Mapped[int] = mapped_column(Integer)
    away_goals: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(8))
    brier: Mapped[float | None] = mapped_column(Float)
    log_loss: Mapped[float | None] = mapped_column(Float)
    ht_home: Mapped[int | None] = mapped_column(Integer)
    ht_away: Mapped[int | None] = mapped_column(Integer)
    ht_brier: Mapped[float | None] = mapped_column(Float)
    ht_log_loss: Mapped[float | None] = mapped_column(Float)
