"""ML işçisi görevleri (Celery, ``ml`` kuyruğu).

    celery -A mi_ml.tasks worker -Q ml --loglevel=INFO --concurrency=1

Zamanlayıcı (``mi_api.worker`` Beat) ``MI_ML_SCHEDULE_ENABLED=true`` iken bu görevleri planlar.
Eğitim zamanlanmaz: yeni model sürümü ``mi-ml train`` ile bilinçli olarak üretilir ve aday olarak
kaydedilir; şampiyon değişikliği yönetim panelinden yapılır.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from mi_api.config import Settings
from mi_api.migrate import sync_url
from mi_api.predictions.models import ModelVersion
from mi_api.worker import app
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from mi_ml.pipeline import predict_scope, settle

log = logging.getLogger(__name__)


def _engine() -> Any:
    return create_engine(sync_url(Settings().database_url.get_secret_value()))


@app.task(name="mi.ml.predict_active")  # type: ignore[untyped-decorator]
def predict_active() -> dict[str, Any]:
    engine = _engine()
    now = datetime.now(UTC)
    summary: dict[str, Any] = {}
    try:
        with Session(engine) as session:
            scopes = session.scalars(
                select(ModelVersion.scope).where(ModelVersion.status == "champion")
            ).all()
        for scope in scopes:
            ids = list(scope["competition_ids"])
            try:
                with Session(engine) as session, session.begin():
                    preds = predict_scope(session, ids, now=now)
                summary[",".join(map(str, ids))] = {
                    "written": len(preds),
                    "published": sum(p.status == "published" for p in preds),
                }
            except Exception as exc:  # bir kapsamın hatası diğerlerini durdurmaz
                log.exception("Tahmin üretilemedi: %s", ids)
                summary[",".join(map(str, ids))] = {"error": type(exc).__name__}
    finally:
        engine.dispose()
    return summary


@app.task(name="mi.ml.settle")  # type: ignore[untyped-decorator]
def settle_task() -> dict[str, int]:
    engine = _engine()
    try:
        with Session(engine) as session, session.begin():
            return {"settled": settle(session, now=datetime.now(UTC))}
    finally:
        engine.dispose()
