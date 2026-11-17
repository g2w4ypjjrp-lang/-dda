"""Ortak arayüzlü 1X2 modelleri ve JSON'a güvenli serileştirme.

Her model ``fit(train_rows, train_matches)`` ve ``predict(rows) -> (n, 3)`` sunar. Tahmin
edilemeyen satır (ör. eğitimde görülmemiş takım) NaN döner; değerlendirme bu satırları dışlar.

Serileştirme pickle **kullanmaz** (veritabanından okunan pickle kod çalıştırabilir): parametreler
JSON, LightGBM modeli kendi metin biçimiyle saklanır.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, Self, TypeVar

import lightgbm as lgb
import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression

from mi_ml.dixon_coles import DixonColes, UnknownTeam
from mi_ml.features import FeatureRow, Match, matrix
from mi_ml.metrics import outcome_label

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
SEED = 42


T = TypeVar("T")


def _require[T](value: T | None, what: str) -> T:
    if value is None:
        raise RuntimeError(f"{what} eğitilmemiş")
    return value


def labels(rows: Sequence[FeatureRow]) -> IntArray:
    return np.array(
        [outcome_label(r.match.home_goals, r.match.away_goals) for r in rows], dtype=np.int64
    )


class Model(Protocol):
    @property
    def name(self) -> str: ...

    def fit(self, rows: Sequence[FeatureRow], played: Sequence[Match]) -> Self: ...

    def predict(self, rows: Sequence[FeatureRow]) -> FloatArray: ...

    def to_json(self) -> dict[str, Any]: ...


@dataclass
class ScoreModel:
    """Poisson (rho=0) veya Dixon-Coles; özellik değil maç sonuçlarıyla eğitilir."""

    fit_rho: bool = True
    xi: float = 0.0019
    model: DixonColes | None = None

    @property
    def name(self) -> str:
        return "dixon_coles" if self.fit_rho else "poisson"

    def fit(self, rows: Sequence[FeatureRow], played: Sequence[Match]) -> ScoreModel:
        as_of = max(m.kickoff_at for m in played)
        self.model = DixonColes(xi=self.xi, fit_rho=self.fit_rho).fit(played, as_of=as_of)
        return self

    def predict(self, rows: Sequence[FeatureRow]) -> FloatArray:
        model = _require(self.model, "Skor modeli")
        out = np.full((len(rows), 3), np.nan)
        for i, r in enumerate(rows):
            try:
                x = model.score_matrix(r.match.home, r.match.away).one_x_two()
            except UnknownTeam:
                continue
            out[i] = (x["home"], x["draw"], x["away"])
        return out

    def to_json(self) -> dict[str, Any]:
        return _require(self.model, "Skor modeli").params()

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ScoreModel:
        teams = sorted(data["teams"])
        dc = DixonColes(xi=data["xi"], l2=data["l2"], fit_rho=data["model"] == "dixon_coles")
        dc.teams = teams
        dc.attack = np.array([data["teams"][t]["attack"] for t in teams])
        dc.defence = np.array([data["teams"][t]["defence"] for t in teams])
        dc.intercept, dc.home_adv, dc.rho = data["intercept"], data["home_adv"], data["rho"]
        dc.n_matches, dc.converged = data["n_matches"], data["converged"]
        return cls(fit_rho=dc.fit_rho, xi=dc.xi, model=dc)


@dataclass
class LinearModel:
    """Çok sınıflı lojistik regresyon. ``elo_logit``: yalnızca Elo farkı; ``logistic``: tüm özellikler."""

    name: str = "logistic"
    features: list[str] | None = None
    c: float = 0.5
    columns: list[str] = field(default_factory=list)
    medians: FloatArray = field(default_factory=lambda: np.zeros(0))
    means: FloatArray = field(default_factory=lambda: np.zeros(0))
    scales: FloatArray = field(default_factory=lambda: np.ones(0))
    coef: FloatArray = field(default_factory=lambda: np.zeros((3, 0)))
    intercept: FloatArray = field(default_factory=lambda: np.zeros(3))

    def _prepare(self, x: FloatArray) -> FloatArray:
        x = np.where(np.isnan(x), self.medians, x)
        result: FloatArray = (x - self.means) / self.scales
        return result

    def fit(self, rows: Sequence[FeatureRow], played: Sequence[Match]) -> LinearModel:
        x, self.columns = matrix(rows, self.features)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(x, axis=0)
        self.medians = np.where(np.isnan(med), 0.0, med)
        filled = np.where(np.isnan(x), self.medians, x)
        self.means = filled.mean(axis=0)
        std = filled.std(axis=0)
        self.scales = np.where(std > 1e-9, std, 1.0)
        clf = LogisticRegression(C=self.c, max_iter=2000)
        clf.fit(self._prepare(x), labels(rows))
        coef = np.zeros((3, len(self.columns)))
        intercept = np.zeros(3)
        for k, cls in enumerate(clf.classes_):
            coef[int(cls)] = clf.coef_[k]
            intercept[int(cls)] = clf.intercept_[k]
        self.coef, self.intercept = coef, intercept
        return self

    def predict(self, rows: Sequence[FeatureRow]) -> FloatArray:
        x, _ = matrix(rows, self.columns)
        z = self._prepare(x) @ self.coef.T + self.intercept
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        out: FloatArray = e / e.sum(axis=1, keepdims=True)
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "c": self.c,
            "columns": self.columns,
            "medians": self.medians.tolist(),
            "means": self.means.tolist(),
            "scales": self.scales.tolist(),
            "coef": self.coef.tolist(),
            "intercept": self.intercept.tolist(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LinearModel:
        return cls(
            name=data["name"],
            c=data["c"],
            columns=list(data["columns"]),
            medians=np.array(data["medians"]),
            means=np.array(data["means"]),
            scales=np.array(data["scales"]),
            coef=np.array(data["coef"]),
            intercept=np.array(data["intercept"]),
        )


GBM_DEFAULTS: dict[str, Any] = {
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_data_in_leaf": 30,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "max_rounds": 600,
}


@dataclass
class GbmModel:
    """LightGBM çok sınıflı sınıflandırıcı; erken durdurma eğitim verisinin son %15'iyle (zaman sırası)."""

    params: dict[str, Any] = field(default_factory=lambda: dict(GBM_DEFAULTS))
    name: str = "gbm"
    columns: list[str] = field(default_factory=list)
    booster: lgb.Booster | None = None
    best_iteration: int = 0

    def _lgb_params(self) -> dict[str, Any]:
        p = {k: v for k, v in self.params.items() if k != "max_rounds"}
        return {
            **p,
            "objective": "multiclass",
            "num_class": 3,
            "verbosity": -1,
            "seed": SEED,
            "deterministic": True,
            "force_row_wise": True,
            "num_threads": 1,
        }

    def fit(self, rows: Sequence[FeatureRow], played: Sequence[Match]) -> GbmModel:
        ordered = sorted(rows, key=lambda r: r.match.kickoff_at)
        x, self.columns = matrix(ordered)
        y = labels(ordered)
        cut = max(int(len(ordered) * 0.85), 1)
        train = lgb.Dataset(x[:cut], y[:cut], feature_name=self.columns, free_raw_data=False)
        valid = lgb.Dataset(x[cut:], y[cut:], reference=train) if cut < len(ordered) else None
        callbacks: list[Callable[..., Any]] = (
            [lgb.early_stopping(50, verbose=False)] if valid is not None else []
        )
        booster = lgb.train(
            self._lgb_params(),
            train,
            num_boost_round=int(self.params.get("max_rounds", 600)),
            valid_sets=[valid] if valid is not None else None,
            callbacks=callbacks,
        )
        self.best_iteration = int(booster.best_iteration or booster.current_iteration())
        # Erken durdurmanın bulduğu tur sayısıyla tüm veriyle yeniden eğit.
        self.booster = lgb.train(
            self._lgb_params(),
            lgb.Dataset(x, y, feature_name=self.columns),
            num_boost_round=max(self.best_iteration, 10),
        )
        return self

    def predict(self, rows: Sequence[FeatureRow]) -> FloatArray:
        booster = _require(self.booster, "LightGBM")
        x, _ = matrix(rows, self.columns)
        out: FloatArray = np.asarray(booster.predict(x), dtype=float).reshape(len(rows), 3)
        return out

    def feature_importance(self) -> dict[str, float]:
        gains = _require(self.booster, "LightGBM").feature_importance(importance_type="gain")
        total = float(gains.sum()) or 1.0
        return {c: float(g) / total for c, g in zip(self.columns, gains, strict=True)}

    def to_json(self) -> dict[str, Any]:
        booster = _require(self.booster, "LightGBM")
        return {
            "params": self.params,
            "columns": self.columns,
            "best_iteration": self.best_iteration,
            "model": booster.model_to_string(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> GbmModel:
        m = cls(params=dict(data["params"]), columns=list(data["columns"]))
        m.best_iteration = int(data["best_iteration"])
        m.booster = lgb.Booster(model_str=data["model"])
        return m


def make(name: str, gbm_params: dict[str, Any] | None = None, xi: float = 0.0019) -> Model:
    if name == "dixon_coles":
        return ScoreModel(fit_rho=True, xi=xi)
    if name == "poisson":
        return ScoreModel(fit_rho=False, xi=xi)
    if name == "elo_logit":
        return LinearModel(name="elo_logit", features=["elo_diff"], c=1.0)
    if name == "logistic":
        return LinearModel(name="logistic", c=0.1)
    if name == "gbm":
        return GbmModel(params={**GBM_DEFAULTS, **(gbm_params or {})})
    raise ValueError(f"Bilinmeyen model: {name}")


def load(name: str, data: dict[str, Any]) -> Model:
    if name in ("dixon_coles", "poisson"):
        return ScoreModel.from_json(data)
    if name in ("elo_logit", "logistic"):
        return LinearModel.from_json(data)
    if name == "gbm":
        return GbmModel.from_json(data)
    raise ValueError(f"Bilinmeyen model: {name}")
