"""Tahmin işleri — Celery (``mi_ml.tasks``) ve komut satırı (``mi-ml predict-active``) ortak kullanır.

Windows tek sunucu kurulumu Celery'siz çalışır: bu işleri Zamanlanmış Görev ile ``mi-ml`` çağırır.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from mi_api.predictions.models import ModelVersion
from sqlalchemy import select
from sqlalchemy.orm import Session

from mi_ml.pipeline import predict_scope, settle

log = logging.getLogger(__name__)


def predict_active(engine: Any, now: datetime) -> dict[str, Any]:
    """Şampiyon modeli olan her kapsam için yaklaşan maçların tahminini yazar.

    Bir kapsamın hatası diğerlerini durdurmaz. Değişmeyen maç yeniden yazılmaz (pipeline)."""
    summary: dict[str, Any] = {}
    with Session(engine) as session:
        scopes = session.scalars(
            select(ModelVersion.scope).where(ModelVersion.status == "champion")
        ).all()
    for scope in scopes:
        ids = list(scope["competition_ids"])
        key = ",".join(map(str, ids))
        try:
            with Session(engine) as session, session.begin():
                preds = predict_scope(session, ids, now=now)
                # Özet oturum kapanmadan hesaplanır (kapanınca nesneler ayrılır; önceki Celery
                # sürümü tahminleri yazıp yine de "hata" raporluyordu).
                summary[key] = {
                    "written": len(preds),
                    "published": sum(p.status == "published" for p in preds),
                }
        except Exception as exc:
            log.exception("Tahmin üretilemedi: %s", ids)
            summary[key] = {"error": type(exc).__name__}
    return summary


def settle_all(engine: Any, now: datetime) -> dict[str, int]:
    with Session(engine) as session, session.begin():
        return {"settled": settle(session, now=now)}
