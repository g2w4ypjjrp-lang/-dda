"""Veritabanı ile eğitim, kayıt, tahmin ve sonuçlandırma işleri.

* ``train_scope``: kapsamdaki (lig) oynanmış maçlarla ``backtest.train`` çalışır, sonuç model kayıt
  defterine yazılır. Kapsamda şampiyon yoksa yeni sürüm şampiyon olur; varsa **aday** (challenger)
  olarak kalır — şampiyonu değiştirmek yönetim panelinden (``models.manage`` + yeniden doğrulama).
* ``predict_scope``: şampiyon sürümle yaklaşan maçlar için tahmin yazar. Aynı maç + aynı sürüm +
  aynı özelliklerle tahmin zaten varsa yenisi yazılmaz. Tahminler değiştirilemez.
* ``settle``: biten maçların tahminlerine 90' sonucu ve 1X2 Brier / log loss ekler (bir kez).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from mi_api.football.models import Fixture
from mi_api.football.quality import freshness
from mi_api.predictions.models import ModelVersion, Prediction, PredictionOutcome, TuningTrial
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from mi_ml import halftime
from mi_ml.backtest import TrainConfig, TrainingResult, summary, train
from mi_ml.data import load_played, load_targets
from mi_ml.metrics import CLASSES, outcome_label
from mi_ml.models import ScoreModel
from mi_ml.predict import Thresholds, load_version, predict

log = logging.getLogger(__name__)


def scope_key(competition_ids: Sequence[int]) -> str:
    return "competition:" + ",".join(str(c) for c in sorted(set(competition_ids)))


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=float))


def register(
    session: Session,
    result: TrainingResult,
    competition_ids: Sequence[int],
    score_model: ScoreModel,
    first_half: dict[str, Any] | None = None,
) -> ModelVersion:
    key = scope_key(competition_ids)
    has_champion = session.scalar(
        select(exists().where(ModelVersion.scope_key == key, ModelVersion.status == "champion"))
    )
    cfg = result.config
    version = ModelVersion(
        scope_key=key,
        scope={"competition_ids": sorted(set(competition_ids))},
        status="challenger" if has_champion else "champion",
        trained_until=result.trained_until,
        seed=cfg.seed,
        config=_json(
            {**cfg.__dict__, "components": list(cfg.components), "gbm_params": result.gbm_params}
        ),
        components=result.weights,
        excluded=result.excluded,
        temperature=result.temperature,
        metrics={**summary(result), "first_half": _json(first_half)}
        if first_half
        else summary(result),
        feature_importance=result.feature_importance,
        data_fingerprint=result.data_fingerprint,
        n_rows=result.n_rows,
        artifact=_json(
            {
                "components": {n: m.to_json() for n, m in result.final_models.items()},
                "score_model": score_model.to_json(),
                "first_half": _json(first_half) if first_half else None,
            }
        ),
    )
    session.add(version)
    session.flush()
    session.add_all(
        TuningTrial(
            model_version_id=version.id,
            number=t["number"],
            state=t["state"],
            value=t["value"],
            params=t["params"],
        )
        for t in result.trials
    )
    return version


def train_scope(session: Session, competition_ids: Sequence[int], cfg: TrainConfig) -> ModelVersion:
    played = load_played(session, competition_ids)
    result = train(played, cfg)
    candidate = result.final_models.get("dixon_coles") or result.final_models.get("poisson")
    score_model = candidate if isinstance(candidate, ScoreModel) else None
    if score_model is None:
        # Skor piyasaları için skor modeli her zaman gerekir (1X2 ensemble'a girmese de).
        score_model = ScoreModel(fit_rho=True, xi=cfg.xi).fit([], played)
    test_from = datetime.fromisoformat(result.periods["test"]["from"])
    first_half = halftime.evaluate(played, test_from, xi=cfg.xi, window_days=cfg.window_days)
    return register(session, result, competition_ids, score_model, first_half)


def predict_scope(
    session: Session,
    competition_ids: Sequence[int],
    *,
    now: datetime,
    horizon: timedelta = timedelta(days=7),
    thresholds: Thresholds | None = None,
) -> list[Prediction]:
    key = scope_key(competition_ids)
    row = session.scalar(
        select(ModelVersion).where(ModelVersion.scope_key == key, ModelVersion.status == "champion")
    )
    if row is None:
        raise LookupError(f"{key} için şampiyon model yok; önce eğitin")
    version = load_version(row)
    history = load_played(session, competition_ids, before=now)
    targets = load_targets(session, competition_ids, now=now, horizon=horizon)
    if not targets:
        return []
    context = {
        t.fixture.id: {
            "stale": freshness(t.fixture.status, t.fixture.kickoff_at, t.fixture.fetched_at, now)[
                "stale"
            ],
            "has_lineups": t.has_lineups,
            "fetched_at": t.fixture.fetched_at.isoformat(),
        }
        for t in targets
    }
    records = predict(
        version,
        history,
        [t.match for t in targets],
        now=now,
        context=context,
        thresholds=thresholds,
    )
    snapshot_base = {
        "model_version_id": version.id,
        "model_trained_until": version.trained_until.isoformat(),
        "history_matches": len(history),
        "history_last_kickoff": history[-1].kickoff_at.isoformat() if history else None,
    }
    written: list[Prediction] = []
    for rec in records:
        duplicate = session.scalar(
            select(
                exists().where(
                    Prediction.fixture_id == rec.fixture_id,
                    Prediction.model_version_id == version.id,
                    Prediction.feature_hash == rec.feature_hash,
                )
            )
        )
        if duplicate:
            continue
        pred = Prediction(
            fixture_id=rec.fixture_id,
            model_version_id=version.id,
            created_at=now,
            kickoff_at=rec.kickoff_at,
            status=rec.status,
            probabilities=_json(rec.probabilities) if rec.probabilities else None,
            components=_json(rec.components),
            uncertainty=_json(rec.uncertainty),
            reliability=rec.reliability,
            data_quality=_json(rec.data_quality),
            model_agreement=rec.model_agreement,
            abstain_reasons=rec.abstain_reasons,
            features=rec.features,
            feature_hash=rec.feature_hash,
            data_snapshot={**snapshot_base, **context[rec.fixture_id]},
        )
        session.add(pred)
        written.append(pred)
    session.flush()
    return written


def _scores(probs: dict[str, float], label: int) -> tuple[float, float]:
    p = np.array([probs[k] for k in CLASSES])
    onehot = np.eye(3)[label]
    return float(((p - onehot) ** 2).sum()), float(-np.log(max(p[label], 1e-15)))


def settle(session: Session, *, now: datetime) -> int:
    stmt = (
        select(Prediction, Fixture)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .where(
            Fixture.status == "finished",
            ~exists().where(PredictionOutcome.prediction_id == Prediction.id),
        )
    )
    count = 0
    for pred, fx in session.execute(stmt):
        if fx.ft_home is not None and fx.ft_away is not None:
            h, a = fx.ft_home, fx.ft_away
        elif (
            fx.status_detail in ("FT", "FINISHED")
            and fx.home_goals is not None
            and fx.away_goals is not None
        ):
            h, a = fx.home_goals, fx.away_goals
        else:
            continue  # 90' skoru bilinmiyor
        label = outcome_label(h, a)
        brier = ll = None
        if pred.status == "published" and pred.probabilities:
            brier, ll = _scores(pred.probabilities["1x2"], label)
        # İY skoru yalnızca 90' skoruyla tutarlıysa yazılır; İY olasılık skoru yalnızca İY
        # piyasaları yayımlanmışsa hesaplanır.
        hh, ha = fx.ht_home, fx.ht_away
        if hh is None or ha is None or hh > h or ha > a:
            hh = ha = None
        ht_brier = ht_ll = None
        fh = (pred.probabilities or {}).get("first_half") or {}
        if hh is not None and ha is not None and pred.status == "published" and fh.get("available"):
            ht_brier, ht_ll = _scores(fh["1x2"], outcome_label(hh, ha))
        session.add(
            PredictionOutcome(
                prediction_id=pred.id,
                settled_at=now,
                home_goals=h,
                away_goals=a,
                outcome=CLASSES[label],
                brier=brier,
                log_loss=ll,
                ht_home=hh,
                ht_away=ha,
                ht_brier=ht_brier,
                ht_log_loss=ht_ll,
            )
        )
        count += 1
    session.flush()
    return count
