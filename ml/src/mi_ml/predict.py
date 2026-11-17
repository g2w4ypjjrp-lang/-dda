"""Tahmin üretimi: ensemble olasılığı, tutarlı piyasalar, belirsizlik, güvenilirlik ve çekimserlik.

**Olasılık ile güvenilirlik ayrı kavramlardır** ve ayrı alanlarda döner:

* ``probabilities``: olayların olasılığı (ör. ev sahibi kazanır %48).
* ``reliability`` (yüksek/orta/düşük): modelin **örneklem dışı test** dönemindeki kalibrasyonu
  (ECE) ve test örneklem sayısına göre.
* ``data_quality``: takımların geçmiş maç sayısı, xG kapsaması, maç verisinin tazeliği, ilk 11.
* ``model_agreement``: bileşen modellerin 1X2 olasılıkları arasındaki en büyük fark.
* ``uncertainty``: Dixon-Coles parametre belirsizliği — maçlar yeniden örneklenerek (bootstrap)
  ``B`` kez yeniden eğitilir; %10–%90 aralığı raporlanır. Bu, **kapsama oranı test edilmiş bir
  güven aralığı değildir**; parametre belirsizliğinin büyüklüğünü gösterir ve böyle etiketlenir.

**Piyasa tutarlılığı:** 1X2 ensemble'dan gelir; diğer piyasalar Dixon-Coles skor matrisinden.
İkisinin tutarlı olması için matris, ev/beraberlik/deplasman bölgeleri ensemble olasılıklarına
eşitlenecek şekilde ölçeklenir (bu kısıtlar altında KL uzaklığını en küçükleyen düzeltme). Böylece
tüm piyasalar tek bir ortak skor dağılımından türetilir.

**Çekimserlik:** aşağıdakilerden biri varsa olasılık yayımlanmaz, nedenleri döner: yetersiz geçmiş,
bilinmeyen takım, bayat veri, model anlaşmazlığı, geniş belirsizlik, zayıf kalibrasyon, küçük test
örneklemi, başlamış maç.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from mi_ml import halftime
from mi_ml.calibration import apply_temperature
from mi_ml.dixon_coles import DixonColes, UnknownTeam
from mi_ml.ensemble import combine
from mi_ml.features import FeatureRow, Match, build_features
from mi_ml.models import Model, ScoreModel, load
from mi_ml.scores import ScoreMatrix

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class Thresholds:
    min_history: int = 5
    max_disagreement: float = 0.20
    max_interval_width: float = 0.35
    max_ece: float = 0.08
    min_test_n: int = 100
    bootstrap: int = 30
    seed: int = 42


@dataclass
class LoadedVersion:
    id: int
    weights: dict[str, float]
    temperature: float
    models: dict[str, Model]
    score_model: ScoreModel
    test_metrics: dict[str, Any]
    trained_until: datetime
    first_half: dict[str, Any] | None = None


def load_version(row: Any) -> LoadedVersion:
    artifact = row.artifact
    return LoadedVersion(
        id=row.id,
        weights={k: float(v) for k, v in row.components.items()},
        temperature=float(row.temperature),
        models={name: load(name, data) for name, data in artifact["components"].items()},
        score_model=ScoreModel.from_json(artifact["score_model"]),
        test_metrics=row.metrics.get("test", {}).get("ensemble", {}),
        trained_until=row.trained_until,
        first_half=artifact.get("first_half"),
    )


def adjust_to_1x2(matrix: ScoreMatrix, target: dict[str, float]) -> ScoreMatrix:
    p = matrix.probs.copy()
    home = np.tril(np.ones_like(p, dtype=bool), -1)
    draw = np.eye(p.shape[0], dtype=bool)
    away = ~(home | draw)
    for region, key in ((home, "home"), (draw, "draw"), (away, "away")):
        mass = p[region].sum()
        if mass > 0:
            p[region] *= target[key] / mass
    p /= p.sum()
    return ScoreMatrix(p, matrix.lambda_home, matrix.lambda_away, matrix.rho, matrix.tail_mass)


def score_matrix_payload(matrix: ScoreMatrix, max_goals: int = 10) -> list[list[float]]:
    p = matrix.probs[: max_goals + 1, : max_goals + 1]
    p = p / p.sum()
    return [[round(float(v), 7) for v in row] for row in p]


def first_half_payload(version: LoadedVersion, matrix: ScoreMatrix) -> dict[str, Any]:
    """İY piyasaları yalnızca İY modeli testte geçtiyse; aksi halde neden yazılır (çekimserlik)."""
    fh = version.first_half
    if not fh:
        return {"available": False, "reasons": ["Bu model sürümünde İY değerlendirmesi yok"]}
    if not fh.get("available") or not fh.get("split"):
        return {
            "available": False,
            "reasons": list(fh.get("reasons") or ["İY modeli doğrulanmadı"]),
        }
    split = (float(fh["split"]["home"]), float(fh["split"]["away"]))
    out = halftime.markets(np.asarray(score_matrix_payload(matrix)), split)
    out["test"] = {
        k: fh.get("test", {}).get(k) for k in ("n", "log_loss", "baseline_log_loss", "ece")
    }
    return out


def reliability_level(test: dict[str, Any], th: Thresholds) -> str:
    n, ece = int(test.get("n", 0)), float(test.get("ece", 1.0))
    if n >= 3 * th.min_test_n and ece <= th.max_ece / 2:
        return "high"
    if n >= th.min_test_n and ece <= th.max_ece:
        return "medium"
    return "low"


def _clean(features: dict[str, float]) -> dict[str, float | None]:
    return {
        k: (None if isinstance(v, float) and math.isnan(v) else round(float(v), 6))
        for k, v in sorted(features.items())
    }


def feature_hash(features: dict[str, float | None]) -> str:
    return hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()


def bootstrap_models(
    history: Sequence[Match], base: ScoreModel, n: int, seed: int
) -> list[DixonColes]:
    if n <= 0 or base.model is None:
        return []
    rng = np.random.default_rng(seed)
    played = list(history)
    as_of = max(m.kickoff_at for m in played)
    models = []
    for _ in range(n):
        sample = [played[i] for i in rng.integers(0, len(played), len(played))]
        models.append(
            DixonColes(xi=base.model.xi, l2=base.model.l2, fit_rho=base.model.fit_rho).fit(
                sample, as_of=as_of
            )
        )
    return models


@dataclass
class PredictionRecord:
    fixture_id: int
    kickoff_at: datetime
    status: str
    probabilities: dict[str, Any] | None
    components: dict[str, dict[str, float]]
    uncertainty: dict[str, Any]
    reliability: str
    data_quality: dict[str, Any]
    model_agreement: float | None
    abstain_reasons: list[dict[str, str]]
    features: dict[str, float | None]
    feature_hash: str
    data_snapshot: dict[str, Any] = field(default_factory=dict)


def predict(
    version: LoadedVersion,
    history: Sequence[Match],
    targets: Sequence[Match],
    *,
    now: datetime,
    context: dict[int, dict[str, Any]] | None = None,
    thresholds: Thresholds | None = None,
) -> list[PredictionRecord]:
    """``context[fixture_id]``: {"stale": bool, "has_lineups": bool, "fetched_at": iso} (Faz 2)."""
    th = thresholds or Thresholds()
    context = context or {}
    rows: list[FeatureRow] = build_features(history, targets)
    comp = {name: m.predict(rows) for name, m in version.models.items()}
    names = list(version.weights)
    boot = bootstrap_models(history, version.score_model, th.bootstrap, th.seed)
    reliability = reliability_level(version.test_metrics, th)
    out: list[PredictionRecord] = []

    for i, row in enumerate(rows):
        m = row.match
        ctx = context.get(m.fixture_id, {})
        reasons: list[dict[str, str]] = []
        component_probs = {
            n: {
                "home": float(comp[n][i, 0]),
                "draw": float(comp[n][i, 1]),
                "away": float(comp[n][i, 2]),
            }
            for n in names
            if not np.isnan(comp[n][i]).any()
        }
        if m.kickoff_at <= now:
            reasons.append({"code": "kickoff_passed", "message": "Maç başlamış; tahmin üretilmez"})
        hist_h, hist_a = row.features["h_n"], row.features["a_n"]
        if min(hist_h, hist_a) < th.min_history:
            reasons.append(
                {
                    "code": "insufficient_history",
                    "message": f"Takımlardan birinin modelde yeterli geçmişi yok ({int(min(hist_h, hist_a))} < {th.min_history} maç)",
                }
            )
        if len(component_probs) < len(names):
            missing = sorted(set(names) - set(component_probs))
            reasons.append(
                {
                    "code": "unknown_team",
                    "message": "Model bu takım(lar)ı tanımıyor: " + ", ".join(missing),
                }
            )
        if ctx.get("stale"):
            reasons.append({"code": "stale_data", "message": "Maç verisi güncel değil"})
        if reliability == "low":
            n_test, ece = (
                version.test_metrics.get("n", 0),
                version.test_metrics.get("ece", float("nan")),
            )
            if n_test < th.min_test_n:
                reasons.append(
                    {
                        "code": "small_validation",
                        "message": f"Model yeterince test edilmedi (test örneklemi {n_test} < {th.min_test_n})",
                    }
                )
            else:
                reasons.append(
                    {
                        "code": "poor_calibration",
                        "message": f"Test döneminde kalibrasyon zayıf (ECE {ece:.3f})",
                    }
                )

        agreement = None
        if len(component_probs) >= 2:
            arr = np.array([[p["home"], p["draw"], p["away"]] for p in component_probs.values()])
            agreement = float((arr.max(axis=0) - arr.min(axis=0)).max())
            if agreement > th.max_disagreement:
                reasons.append(
                    {
                        "code": "model_disagreement",
                        "message": f"Modeller arasında büyük fark ({agreement:.0%})",
                    }
                )

        probabilities = None
        uncertainty: dict[str, Any] = {}
        if len(component_probs) == len(names):
            ens = combine(
                [comp[n][i : i + 1] for n in names], np.array([version.weights[n] for n in names])
            )
            final = apply_temperature(ens, version.temperature)[0]
            target = {"home": float(final[0]), "draw": float(final[1]), "away": float(final[2])}
            try:
                base = version.score_model.model.score_matrix(m.home, m.away)  # type: ignore[union-attr]
            except UnknownTeam:
                base = None
                if not any(r["code"] == "unknown_team" for r in reasons):
                    reasons.append(
                        {"code": "unknown_team", "message": "Skor modeli bu takım(lar)ı tanımıyor"}
                    )
            if base is not None:
                matrix = adjust_to_1x2(base, target)
                probabilities = matrix.markets()
                probabilities["1x2"] = target
                # Tam ortak skor dağılımı (0..10 gol): kupon motoru aynı maçtaki birden fazla
                # seçimin birleşik olasılığını buradan kesin hesaplar. Kuyruk ≈ 0, normalize edilir.
                probabilities["score_matrix"] = score_matrix_payload(matrix)
                probabilities["first_half"] = first_half_payload(version, matrix)
                if boot:
                    point = base.one_x_two()
                    samples = []
                    for bm in boot:
                        try:
                            x = bm.score_matrix(m.home, m.away).one_x_two()
                        except UnknownTeam:
                            continue
                        samples.append([x[k] - point[k] for k in ("home", "draw", "away")])
                    if samples:
                        d = np.array(samples)
                        lo, hi = np.quantile(d, 0.1, axis=0), np.quantile(d, 0.9, axis=0)
                        interval = {
                            k: [
                                max(0.0, target[k] + float(lo[j])),
                                min(1.0, target[k] + float(hi[j])),
                            ]
                            for j, k in enumerate(("home", "draw", "away"))
                        }
                        width = max(b - a for a, b in interval.values())
                        uncertainty = {
                            "method": "dixon_coles_bootstrap",
                            "label": "Parametre belirsizliği (%10–%90, bootstrap); kapsama oranı test edilmiş güven aralığı değildir",
                            "samples": len(samples),
                            "interval_1x2": interval,
                            "max_width": width,
                        }
                        if width > th.max_interval_width:
                            reasons.append(
                                {
                                    "code": "wide_interval",
                                    "message": f"Belirsizlik aralığı çok geniş ({width:.0%})",
                                }
                            )

        xg_cover = (
            sum(
                1
                for k in ("h_xgf_5", "a_xgf_5")
                if not math.isnan(row.features.get(k, float("nan")))
            )
            / 2
        )
        data_quality = {
            "home_history": int(hist_h),
            "away_history": int(hist_a),
            "xg_coverage": xg_cover,
            "lineups_known": bool(ctx.get("has_lineups", False)),
            "fixture_fetched_at": ctx.get("fetched_at"),
            "stale": bool(ctx.get("stale", False)),
        }
        features = _clean(row.features)
        status = "abstained" if reasons else "published"
        out.append(
            PredictionRecord(
                fixture_id=m.fixture_id,
                kickoff_at=m.kickoff_at,
                status=status,
                probabilities=probabilities if status == "published" else None,
                components=component_probs,
                uncertainty=uncertainty,
                reliability=reliability,
                data_quality=data_quality,
                model_agreement=agreement,
                abstain_reasons=reasons,
                features=features,
                feature_hash=feature_hash(features),
            )
        )
    return out
