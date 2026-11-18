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
from mi_api.worker import app
from sqlalchemy import create_engine

from mi_ml import jobs

log = logging.getLogger(__name__)


def _engine() -> Any:
    return create_engine(sync_url(Settings().database_url.get_secret_value()))


@app.task(name="mi.ml.predict_active")  # type: ignore[untyped-decorator]
def predict_active() -> dict[str, Any]:
    engine = _engine()
    try:
        return jobs.predict_active(engine, datetime.now(UTC))
    finally:
        engine.dispose()


@app.task(name="mi.ml.settle")  # type: ignore[untyped-decorator]
def settle_task() -> dict[str, int]:
    engine = _engine()
    try:
        return jobs.settle_all(engine, datetime.now(UTC))
    finally:
        engine.dispose()
