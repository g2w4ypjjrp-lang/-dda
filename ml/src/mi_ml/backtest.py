"""Eğitim ve değerlendirme hattı: Optuna + walk-forward backtest + ensemble + kalibrasyon.

Zaman çizgisi (eşik maçlar: her iki takımın da en az ``min_history`` geçmiş maçı olanlar)::

    |------------ geliştirme (dev) --------------|------ test (son %20) ------|
    |---- ayarlama (Optuna) ----|-- doğrulama --|

1. **Optuna** yalnızca ayarlama bölgesinde, genişleyen pencereli zaman sıralı çapraz doğrulamayla
   (her katmanda eğitim = katman başlangıcından önceki maçlar) LightGBM hiperparametrelerini seçer.
   ``seed=42``, TPE örnekleyici, medyan budama; her deneme kaydedilir.
2. **Doğrulama** bölgesinde tüm modeller walk-forward (ör. 30 günlük pencereler, her pencere öncesi
   yeniden eğitim) örneklem dışı tahmin üretir. Ensemble ağırlıkları ve sıcaklık burada öğrenilir.
   Doğrulamada tekdüze tahminden (log 3) iyi olmayan veya ağırlığı %2'nin altında kalan model
   ensemble'a alınmaz.
3. **Test** bölgesi hiçbir seçimde kullanılmaz; aynı walk-forward düzeniyle her model ve ensemble
   ölçülür. Raporlanan metrikler budur.
4. Üretim modeli, seçilen ayarlarla tüm veriyle yeniden eğitilir.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import optuna
from numpy.typing import NDArray

from mi_ml.calibration import TemperatureScaler
from mi_ml.ensemble import combine, fit_weights
from mi_ml.features import RESULT_DELAY, FeatureRow, Match, build_features
from mi_ml.metrics import evaluate, log_loss
from mi_ml.models import SEED, GbmModel, Model, labels, make

log = logging.getLogger(__name__)
FloatArray = NDArray[np.float64]
COMPONENTS = ("elo_logit", "poisson", "dixon_coles", "logistic", "gbm")
UNIFORM_LOG_LOSS = math.log(3)


@dataclass
class TrainConfig:
    test_fraction: float = 0.2
    val_fraction: float = 0.3  # dev bölgesinin son kısmı
    window_days: int = 30
    min_history: int = 5
    n_trials: int = 100
    cv_folds: int = 3
    seed: int = SEED
    xi: float = 0.0019
    components: tuple[str, ...] = COMPONENTS
    min_weight: float = 0.02


@dataclass
class TrainingResult:
    config: TrainConfig
    gbm_params: dict[str, Any]
    trials: list[dict[str, Any]]
    weights: dict[str, float]
    excluded: dict[str, str]
    temperature: float
    validation: dict[str, Any]
    test: dict[str, Any]
    final_models: dict[str, Model]
    feature_importance: dict[str, float]
    data_fingerprint: str
    trained_until: datetime
    n_rows: int
    periods: dict[str, Any] = field(default_factory=dict)


def fingerprint(matches: Sequence[Match]) -> str:
    h = hashlib.sha256()
    for m in sorted(matches, key=lambda m: (m.kickoff_at, m.fixture_id)):
        h.update(
            f"{m.fixture_id}|{m.kickoff_at.isoformat()}|{m.home}|{m.away}|{m.home_goals}|{m.away_goals}\n".encode()
        )
    return h.hexdigest()


def eligible(rows: Sequence[FeatureRow], min_history: int) -> list[FeatureRow]:
    return [
        r for r in rows if r.features["h_n"] >= min_history and r.features["a_n"] >= min_history
    ]


def _windows(start: datetime, end: datetime, days: int) -> list[tuple[datetime, datetime]]:
    out = []
    t = start
    while t <= end:
        out.append((t, t + timedelta(days=days)))
        t += timedelta(days=days)
    return out


def walk_forward(
    factory: Callable[[], Model],
    rows: Sequence[FeatureRow],
    played: Sequence[Match],
    targets: Sequence[FeatureRow],
    window_days: int,
) -> FloatArray:
    """``targets`` için örneklem dışı tahmin: her pencere öncesi, sonucu kesinleşmiş verilerle yeniden eğitim."""
    out = np.full((len(targets), 3), np.nan)
    if not targets:
        return out
    order = sorted(range(len(targets)), key=lambda i: targets[i].match.kickoff_at)
    first, last = targets[order[0]].match.kickoff_at, targets[order[-1]].match.kickoff_at
    for lo, hi in _windows(first, last, window_days):
        idx = [i for i in order if lo <= targets[i].match.kickoff_at < hi]
        if not idx:
            continue
        cutoff = lo - RESULT_DELAY
        train_rows = [r for r in rows if r.match.kickoff_at <= cutoff]
        train_played = [m for m in played if m.kickoff_at <= cutoff]
        if len(train_rows) < 30 or len(train_played) < 30:
            continue
        model = factory().fit(train_rows, train_played)
        out[idx] = model.predict([targets[i] for i in idx])
    return out


def _tune(
    rows: Sequence[FeatureRow], played: Sequence[Match], cfg: TrainConfig
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if cfg.n_trials <= 0 or len(rows) < 120:
        return {}, []
    ordered = sorted(rows, key=lambda r: r.match.kickoff_at)
    n = len(ordered)
    fold_edges = [int(n * (0.5 + 0.5 * k / cfg.cv_folds)) for k in range(cfg.cv_folds + 1)]

    def objective(trial: optuna.Trial) -> float:
        params = {
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 4, 48),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 10, 120),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": 1,
            "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 30.0, log=True),
            "max_rounds": 600,
        }
        losses = []
        for k in range(cfg.cv_folds):
            train, test = ordered[: fold_edges[k]], ordered[fold_edges[k] : fold_edges[k + 1]]
            if not test:
                continue
            model = GbmModel(params=params).fit(train, played)
            losses.append(log_loss(model.predict(test), labels(test)))
            trial.report(float(np.mean(losses)), k)
            if trial.should_prune():
                raise optuna.TrialPruned
        return float(np.mean(losses))

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=cfg.seed),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=1),
    )
    study.optimize(objective, n_trials=cfg.n_trials)
    trials = [
        {"number": t.number, "state": t.state.name, "value": t.value, "params": t.params}
        for t in study.trials
    ]
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    best = study.best_params if completed else {}
    return {**best, "bagging_freq": 1, "max_rounds": 600} if best else {}, trials


def _component_predictions(
    names: Sequence[str],
    rows: Sequence[FeatureRow],
    played: Sequence[Match],
    targets: Sequence[FeatureRow],
    cfg: TrainConfig,
    gbm_params: dict[str, Any],
) -> dict[str, FloatArray]:
    return {
        name: walk_forward(
            functools.partial(make, name, gbm_params, cfg.xi),
            rows,
            played,
            targets,
            cfg.window_days,
        )
        for name in names
    }


def train(matches: Sequence[Match], cfg: TrainConfig | None = None) -> TrainingResult:
    cfg = cfg or TrainConfig()
    played = sorted((m for m in matches if m.played), key=lambda m: m.kickoff_at)
    if len(played) < 200:
        raise ValueError(f"Eğitim için yetersiz veri: {len(played)} maç (en az 200)")
    all_rows = build_features(played)
    rows = sorted(eligible(all_rows, cfg.min_history), key=lambda r: r.match.kickoff_at)
    n = len(rows)
    test_start = int(n * (1 - cfg.test_fraction))
    val_start = int(test_start * (1 - cfg.val_fraction))
    tune_rows, val_rows, test_rows = rows[:val_start], rows[val_start:test_start], rows[test_start:]
    if min(len(val_rows), len(test_rows)) < 50:
        raise ValueError("Doğrulama ve test için yeterli maç yok (her biri en az 50)")

    gbm_params, trials = _tune(tune_rows, played, cfg) if "gbm" in cfg.components else ({}, [])
    log.info("Optuna tamamlandı: %d deneme", len(trials))

    # --- Doğrulama: ensemble ağırlıkları ve sıcaklık -------------------------------------------
    val_preds = _component_predictions(cfg.components, rows, played, val_rows, cfg, gbm_params)
    y_val = labels(val_rows)
    mask = np.all([~np.isnan(p).any(axis=1) for p in val_preds.values()], axis=0)
    validation = {name: evaluate(p[mask], y_val[mask]) for name, p in val_preds.items()}
    excluded = {
        name: f"doğrulama log loss {validation[name]['log_loss']:.4f} ≥ tekdüze {UNIFORM_LOG_LOSS:.4f}"
        for name in cfg.components
        if validation[name]["log_loss"] >= UNIFORM_LOG_LOSS
    }
    kept = [c for c in cfg.components if c not in excluded]
    if not kept:
        raise ValueError("Hiçbir model doğrulamada tekdüze tahminden iyi değil; üretime alınmaz")
    weights = fit_weights([val_preds[c][mask] for c in kept], y_val[mask])
    low = [c for c, w in zip(kept, weights, strict=True) if w < cfg.min_weight]
    for c in low:
        excluded[c] = f"ensemble ağırlığı < {cfg.min_weight:.0%} (katkı yok)"
    kept = [c for c in kept if c not in low]
    weights = fit_weights([val_preds[c][mask] for c in kept], y_val[mask])
    ens_val = combine([val_preds[c][mask] for c in kept], weights)
    scaler = TemperatureScaler.fit(ens_val, y_val[mask])
    validation["ensemble"] = evaluate(scaler.transform(ens_val), y_val[mask])

    # --- Test: hiçbir seçimde kullanılmamış dönem ---------------------------------------------
    test_preds = _component_predictions(cfg.components, rows, played, test_rows, cfg, gbm_params)
    y_test = labels(test_rows)
    tmask = np.all([~np.isnan(p).any(axis=1) for p in test_preds.values()], axis=0)
    test = {name: evaluate(p[tmask], y_test[tmask]) for name, p in test_preds.items()}
    ens_test = scaler.transform(combine([test_preds[c][tmask] for c in kept], weights))
    test["ensemble"] = evaluate(ens_test, y_test[tmask])
    prior = np.bincount(labels(tune_rows), minlength=3) / len(tune_rows)
    test["baseline_class_frequency"] = evaluate(
        np.tile(prior, (int(tmask.sum()), 1)), y_test[tmask]
    )

    # --- Üretim modelleri: tüm veriyle ---------------------------------------------------------
    final = {c: make(c, gbm_params, cfg.xi).fit(rows, played) for c in kept}
    gbm = final.get("gbm")
    importance = gbm.feature_importance() if isinstance(gbm, GbmModel) else {}

    return TrainingResult(
        config=cfg,
        gbm_params=gbm_params,
        trials=trials,
        weights={c: float(w) for c, w in zip(kept, weights, strict=True)},
        excluded=excluded,
        temperature=scaler.temperature,
        validation=validation,
        test=test,
        final_models=final,
        feature_importance=importance,
        data_fingerprint=fingerprint(played),
        trained_until=played[-1].kickoff_at,
        n_rows=n,
        periods={
            "tune": _span(tune_rows),
            "validation": _span(val_rows),
            "test": _span(test_rows),
        },
    )


def _span(rows: Sequence[FeatureRow]) -> dict[str, Any]:
    return {
        "from": rows[0].match.kickoff_at.isoformat(),
        "to": rows[-1].match.kickoff_at.isoformat(),
        "n": len(rows),
    }


def summary(result: TrainingResult) -> dict[str, Any]:
    """Kayıt için JSON'a uygun özet (güvenilirlik diyagramı dahil)."""
    data: dict[str, Any] = json.loads(
        json.dumps(
            {
                "weights": result.weights,
                "excluded": result.excluded,
                "temperature": result.temperature,
                "validation": result.validation,
                "test": result.test,
                "periods": result.periods,
                "n_rows": result.n_rows,
            },
            default=float,
        )
    )
    return data
