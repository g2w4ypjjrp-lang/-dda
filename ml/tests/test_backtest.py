"""Uçtan uca eğitim: Optuna + walk-forward + ensemble + kalibrasyon (sentetik lig)."""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pytest

from mi_ml.backtest import TrainConfig, TrainingResult, fingerprint, summary, train
from mi_ml.features import build_features
from mi_ml.models import load
from synthetic import league_matches


@pytest.fixture(scope="module")
def result() -> TrainingResult:
    return train(
        league_matches(n_teams=12, seasons=4), TrainConfig(n_trials=6, cv_folds=2, window_days=45)
    )


def test_periods_are_chronological_and_disjoint(result: TrainingResult) -> None:
    p = result.periods
    assert datetime.fromisoformat(p["tune"]["to"]) <= datetime.fromisoformat(
        p["validation"]["from"]
    )
    assert datetime.fromisoformat(p["validation"]["to"]) <= datetime.fromisoformat(
        p["test"]["from"]
    )
    assert p["test"]["n"] >= 50


def test_optuna_trials_recorded(result: TrainingResult) -> None:
    assert len(result.trials) == 6
    assert {t["state"] for t in result.trials} <= {"COMPLETE", "PRUNED"}
    assert result.gbm_params and 0.01 <= result.gbm_params["learning_rate"] <= 0.15


def test_ensemble_and_metrics(result: TrainingResult) -> None:
    assert sum(result.weights.values()) == pytest.approx(1.0)
    assert all(w >= 0.02 for w in result.weights.values())
    assert set(result.weights) | set(result.excluded) == {
        "elo_logit",
        "poisson",
        "dixon_coles",
        "logistic",
        "gbm",
    }
    assert 0.25 <= result.temperature <= 4.0
    test = result.test
    for name in ("ensemble", "dixon_coles", "baseline_class_frequency"):
        assert {
            "n",
            "brier",
            "log_loss",
            "ece",
            "accuracy",
            "reliability",
            "confusion_matrix",
        } <= set(test[name])
    assert test["ensemble"]["n"] == test["baseline_class_frequency"]["n"] > 50
    # Veri gerçekten Dixon-Coles sürecinden üretildiği için model, sınıf frekansından iyi olmalı.
    assert test["dixon_coles"]["log_loss"] < test["baseline_class_frequency"]["log_loss"]
    assert test["ensemble"]["log_loss"] < np.log(3)


def test_summary_is_json_and_models_roundtrip(result: TrainingResult) -> None:
    data = summary(result)
    json.dumps(data)
    rows = build_features(league_matches(n_teams=12, seasons=4))[-20:]
    for name, model in result.final_models.items():
        restored = load(name, json.loads(json.dumps(model.to_json())))
        assert np.allclose(restored.predict(rows), model.predict(rows), equal_nan=True)


def test_fingerprint_and_minimum_data() -> None:
    matches = league_matches(n_teams=6, seasons=1)
    assert fingerprint(matches) == fingerprint(list(reversed(matches)))
    with pytest.raises(ValueError, match="yetersiz"):
        train(matches[:100])
