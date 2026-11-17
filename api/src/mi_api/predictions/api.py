"""Tahmin ve model yönetimi API'si.

Herkese açık (abonelik kısıtları Faz 6'da):
* ``GET /v1/predictions?date=`` — Türkiye gününe göre maç başına en son tahmin
* ``GET /v1/predictions/fixtures/{id}`` — bir maçın en son tahmini (+ sonuç, varsa)
* ``GET /v1/predictions/performance?days=`` — **gerçekleşmiş** tahmin performansı; yalnızca
  sonuçlanmış, yayımlanmış tahminlerden hesaplanır. Veri yoksa metrik uydurulmaz.

Yönetim (Model Lab):
* ``GET /admin/v1/models`` / ``GET /admin/v1/models/{id}`` — ``models.read``
* ``POST /admin/v1/models/{id}/promote`` — ``models.manage`` (hassas: yeniden doğrulama); şampiyonu
  değiştirir. Geri alma = eski sürümü yeniden şampiyon yapmak. Denetim kaydına yazılır.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from mi_api import audit
from mi_api.context import DbDep, MetaDep, Principal, ServicesDep, require_permission
from mi_api.errors import ApiError
from mi_api.football.api import TR, tr_day_bounds
from mi_api.predictions.models import ModelVersion, Prediction, PredictionOutcome, TuningTrial

DISCLAIMER = (
    "Olasılıklar istatistiksel tahmindir; kesin sonuç veya kazanç garantisi değildir. "
    "Bu platform gerçek bahis işlemi yapmaz."
)
RELIABILITY_LABELS = {"high": "Yüksek", "medium": "Orta", "low": "Düşük"}
CLASSES = ("home", "draw", "away")


def _version_brief(v: ModelVersion) -> dict[str, Any]:
    test = (v.metrics or {}).get("test", {}).get("ensemble", {})
    return {
        "id": v.id,
        "scope_key": v.scope_key,
        "status": v.status,
        "created_at": v.created_at.isoformat(),
        "trained_until": v.trained_until.isoformat(),
        "components": v.components,
        "excluded": v.excluded,
        "temperature": v.temperature,
        "n_rows": v.n_rows,
        "test": {k: test.get(k) for k in ("n", "log_loss", "brier", "ece", "accuracy")},
        "promoted_at": v.promoted_at.isoformat() if v.promoted_at else None,
    }


def prediction_view(
    p: Prediction, v: ModelVersion, outcome: PredictionOutcome | None
) -> dict[str, Any]:
    return {
        "id": p.id,
        "fixture_id": p.fixture_id,
        "created_at": p.created_at.isoformat(),
        "kickoff_at": p.kickoff_at.isoformat(),
        "kickoff_local": p.kickoff_at.astimezone(TR).isoformat(),
        "status": p.status,
        "probabilities": p.probabilities,
        "reliability": {"level": p.reliability, "label": RELIABILITY_LABELS[p.reliability]},
        "data_quality": p.data_quality,
        "model_agreement": p.model_agreement,
        "uncertainty": p.uncertainty,
        "abstain_reasons": p.abstain_reasons,
        "components": p.components,
        "model": {
            "version_id": v.id,
            "status": v.status,
            "trained_until": v.trained_until.isoformat(),
            "components": v.components,
        },
        "outcome": {
            "home_goals": outcome.home_goals,
            "away_goals": outcome.away_goals,
            "result": outcome.outcome,
            "brier": outcome.brier,
            "log_loss": outcome.log_loss,
            "settled_at": outcome.settled_at.isoformat(),
        }
        if outcome
        else None,
        "disclaimer": DISCLAIMER,
    }


def _latest_per_fixture() -> Any:
    return (
        select(Prediction.id)
        .ext(distinct_on(Prediction.fixture_id))
        .order_by(Prediction.fixture_id, Prediction.created_at.desc(), Prediction.id.desc())
    )


async def _views(db: AsyncSession, ids_stmt: Any) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Prediction, ModelVersion, PredictionOutcome)
            .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
            .outerjoin(PredictionOutcome, PredictionOutcome.prediction_id == Prediction.id)
            .where(Prediction.id.in_(ids_stmt))
            .order_by(Prediction.kickoff_at, Prediction.fixture_id)
        )
    ).all()
    return [prediction_view(p, v, o) for p, v, o in rows]


def _calibration(rows: list[tuple[list[float], int]], bins: int = 10) -> list[dict[str, Any]]:
    edges = [i / bins for i in range(bins + 1)]
    out = []
    for i in range(bins):
        sel = [
            (max(p), int(p.index(max(p)) == y))
            for p, y in rows
            if (edges[i] < max(p) <= edges[i + 1]) or (i == 0 and max(p) <= edges[1])
        ]
        if sel:
            out.append(
                {
                    "bin_low": edges[i],
                    "bin_high": edges[i + 1],
                    "mean_confidence": sum(c for c, _ in sel) / len(sel),
                    "observed_rate": sum(h for _, h in sel) / len(sel),
                    "count": len(sel),
                }
            )
    return out


def create_predictions_router() -> APIRouter:
    router = APIRouter(tags=["predictions"])

    @router.get("/v1/predictions")
    async def list_predictions(
        db: DbDep, services: ServicesDep, day: Annotated[date | None, Query(alias="date")] = None
    ) -> dict[str, Any]:
        local_day = day or services.clock().astimezone(TR).date()
        start, end = tr_day_bounds(local_day)
        ids = _latest_per_fixture().where(
            Prediction.kickoff_at >= start, Prediction.kickoff_at < end
        )
        items = await _views(db, ids.subquery().select())
        return {"date": local_day.isoformat(), "items": items, "disclaimer": DISCLAIMER}

    @router.get("/v1/predictions/fixtures/{fixture_id}")
    async def fixture_prediction(fixture_id: int, db: DbDep) -> dict[str, Any]:
        ids = _latest_per_fixture().where(Prediction.fixture_id == fixture_id)
        items = await _views(db, ids.subquery().select())
        if not items:
            raise ApiError(404, "no_prediction", "Bu maç için tahmin yok")
        return items[0]

    @router.get("/v1/predictions/performance")
    async def performance(
        db: DbDep, services: ServicesDep, days: Annotated[int, Query(ge=1, le=3650)] = 365
    ) -> dict[str, Any]:
        since = services.clock() - timedelta(days=days)
        rows = (
            await db.execute(
                select(Prediction.status, Prediction.probabilities, PredictionOutcome)
                .join(PredictionOutcome, PredictionOutcome.prediction_id == Prediction.id)
                .where(PredictionOutcome.settled_at >= since)
            )
        ).all()
        published = [(p, o) for s, p, o in rows if s == "published" and p]
        abstained = sum(1 for s, _, _ in rows if s == "abstained")
        if not published:
            return {
                "data_status": "no_settled_predictions",
                "detail": "Henüz sonuçlanmış tahmin yok; performans metriği gösterilmez.",
                "settled_published": 0,
                "settled_abstained": abstained,
                "window_days": days,
            }
        pairs = [
            ([float(p["1x2"][k]) for k in CLASSES], CLASSES.index(o.outcome)) for p, o in published
        ]
        n = len(pairs)
        return {
            "data_status": "ok",
            "window_days": days,
            "settled_published": n,
            "settled_abstained": abstained,
            "brier": sum(o.brier or 0.0 for _, o in published) / n,
            "log_loss": sum(o.log_loss or 0.0 for _, o in published) / n,
            "accuracy": sum(1 for p, y in pairs if p.index(max(p)) == y) / n,
            "uniform_log_loss": math.log(3),
            "reliability": _calibration(pairs),
            "note": (
                "Yalnızca maç başlamadan önce yayımlanmış ve sonuçlanmış tahminler; "
                "geçmiş tahminler değiştirilemez."
            ),
        }

    # --- Model Lab ------------------------------------------------------------------------------

    @router.get("/admin/v1/models")
    async def list_models(
        db: DbDep,
        _: Principal = Depends(require_permission("models.read")),
        scope_key: Annotated[str | None, Query(max_length=64)] = None,
    ) -> dict[str, Any]:
        stmt = select(ModelVersion).order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc())
        if scope_key:
            stmt = stmt.where(ModelVersion.scope_key == scope_key)
        versions = (await db.execute(stmt.limit(200))).scalars().all()
        champions = {v.scope_key: v for v in versions if v.status == "champion"}
        items = []
        for v in versions:
            brief = _version_brief(v)
            champ = champions.get(v.scope_key)
            if v.status == "challenger" and champ is not None:
                a, b = brief["test"].get("log_loss"), _version_brief(champ)["test"].get("log_loss")
                brief["vs_champion"] = {
                    "champion_id": champ.id,
                    "log_loss_delta": (a - b) if a is not None and b is not None else None,
                    "note": "Test dönemleri farklı olabilir (eğitim kesim tarihlerine bakın)",
                }
            items.append(brief)
        return {"items": items}

    @router.get("/admin/v1/models/{version_id}")
    async def get_model(
        version_id: int, db: DbDep, _: Principal = Depends(require_permission("models.read"))
    ) -> dict[str, Any]:
        v = await db.get(ModelVersion, version_id)
        if v is None:
            raise ApiError(404, "not_found", "Model sürümü bulunamadı")
        trials = (
            (
                await db.execute(
                    select(TuningTrial)
                    .where(TuningTrial.model_version_id == v.id)
                    .order_by(TuningTrial.number)
                )
            )
            .scalars()
            .all()
        )
        predictions = (
            await db.execute(select(func.count()).where(Prediction.model_version_id == v.id))
        ).scalar_one()
        return {
            **_version_brief(v),
            "config": v.config,
            "metrics": v.metrics,
            "feature_importance": v.feature_importance,
            "data_fingerprint": v.data_fingerprint,
            "seed": v.seed,
            "predictions": predictions,
            "trials": [
                {"number": t.number, "state": t.state, "value": t.value, "params": t.params}
                for t in trials
            ],
        }

    @router.post("/admin/v1/models/{version_id}/promote")
    async def promote(
        version_id: int,
        db: DbDep,
        services: ServicesDep,
        meta: MetaDep,
        admin: Principal = Depends(require_permission("models.manage")),
    ) -> dict[str, Any]:
        v = await db.get(ModelVersion, version_id, with_for_update=True)
        if v is None:
            raise ApiError(404, "not_found", "Model sürümü bulunamadı")
        if v.status == "champion":
            raise ApiError(409, "already_champion", "Bu sürüm zaten şampiyon")
        if not (v.metrics or {}).get("test", {}).get("ensemble", {}).get("n"):
            raise ApiError(409, "not_evaluated", "Test metriği olmayan sürüm şampiyon yapılamaz")
        previous = (
            await db.execute(
                select(ModelVersion.id).where(
                    ModelVersion.scope_key == v.scope_key, ModelVersion.status == "champion"
                )
            )
        ).scalar_one_or_none()
        await db.execute(
            update(ModelVersion)
            .where(ModelVersion.scope_key == v.scope_key, ModelVersion.status == "champion")
            .values(status="retired")
        )
        await db.flush()
        v.status = "champion"
        v.promoted_at = services.clock()
        v.promoted_by = admin.user.id
        await audit.record(
            db, "admin.model_promoted", actor_type="admin", actor_id=admin.actor_id,
            target_type="model_version", target_id=str(v.id), ip=meta.ip,
            details={"scope_key": v.scope_key, "previous_champion": previous},
        )  # fmt: skip
        return _version_brief(v)

    return router
