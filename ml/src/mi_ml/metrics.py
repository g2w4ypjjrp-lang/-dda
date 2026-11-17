"""Olasılık tahmini değerlendirme metrikleri (sınıflar: 0 = ev, 1 = beraberlik, 2 = deplasman).

Doğruluk (accuracy) tek başına başarı ölçüsü değildir; olasılık kalitesi için Brier, log loss ve
kalibrasyon (ECE, güvenilirlik diyagramı) birlikte raporlanır. Her raporda örneklem sayısı vardır.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
CLASSES = ("home", "draw", "away")
EPS = 1e-15


def _check(probs: FloatArray, y: IntArray) -> None:
    if probs.ndim != 2 or probs.shape[1] != 3 or probs.shape[0] != y.shape[0]:
        raise ValueError("Olasılıklar (n, 3), etiketler (n,) olmalı")
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("Her satırdaki olasılıkların toplamı 1 olmalı")


def brier(probs: FloatArray, y: IntArray) -> float:
    """Çok sınıflı Brier skoru: Σ_k (p_k − o_k)², örnekler üzerinden ortalama (0 en iyi, 2 en kötü)."""
    _check(probs, y)
    onehot = np.eye(3)[y]
    return float(((probs - onehot) ** 2).sum(axis=1).mean())


def log_loss(probs: FloatArray, y: IntArray) -> float:
    _check(probs, y)
    return float(-np.log(np.clip(probs[np.arange(len(y)), y], EPS, 1.0)).mean())


def reliability(probs: FloatArray, y: IntArray, bins: int = 10) -> list[dict[str, float]]:
    """En yüksek olasılıklı sınıfın güveni ile gerçekleşme oranı (eşit genişlikte kutular)."""
    conf = probs.max(axis=1)
    hit = (probs.argmax(axis=1) == y).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for i in range(bins):
        mask = (conf > edges[i]) & (conf <= edges[i + 1]) if i else (conf >= 0) & (conf <= edges[1])
        if mask.any():
            rows.append(
                {
                    "bin_low": float(edges[i]),
                    "bin_high": float(edges[i + 1]),
                    "mean_confidence": float(conf[mask].mean()),
                    "observed_rate": float(hit[mask].mean()),
                    "count": int(mask.sum()),
                }
            )
    return rows


def ece(probs: FloatArray, y: IntArray, bins: int = 10) -> float:
    rows = reliability(probs, y, bins)
    n = len(y)
    return float(sum(r["count"] / n * abs(r["mean_confidence"] - r["observed_rate"]) for r in rows))


def classwise_ece(probs: FloatArray, y: IntArray, bins: int = 10) -> dict[str, float]:
    out = {}
    edges = np.linspace(0, 1, bins + 1)
    for k, name in enumerate(CLASSES):
        p = probs[:, k]
        o = (y == k).astype(float)
        idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
        total = 0.0
        for b in range(bins):
            mask = idx == b
            if mask.any():
                total += mask.mean() * abs(p[mask].mean() - o[mask].mean())
        out[name] = float(total)
    return out


def evaluate(probs: FloatArray, y: IntArray) -> dict[str, Any]:
    _check(probs, y)
    pred = probs.argmax(axis=1)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y, pred, labels=[0, 1, 2], average="macro", zero_division=0
    )
    return {
        "n": len(y),
        "brier": brier(probs, y),
        "log_loss": log_loss(probs, y),
        "accuracy": float((pred == y).mean()),
        "precision_macro": float(precision),
        "recall_macro": float(recall),
        "f1_macro": float(f1),
        "ece": ece(probs, y),
        "classwise_ece": classwise_ece(probs, y),
        "reliability": reliability(probs, y),
        "confusion_matrix": confusion_matrix(y, pred, labels=[0, 1, 2]).tolist(),
        "class_rates": {name: float((y == k).mean()) for k, name in enumerate(CLASSES)},
    }


def outcome_label(home_goals: int, away_goals: int) -> int:
    if home_goals > away_goals:
        return 0
    if home_goals == away_goals:
        return 1
    return 2
