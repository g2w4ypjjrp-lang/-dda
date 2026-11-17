"""Ensemble: modellerin olasılıklarının ağırlıklı ortalaması (doğrusal havuz).

Ağırlıklar rastgele atanmaz: kronolojik doğrulama dönemindeki tahminlerde log loss'u en küçük
yapan, toplamı 1 olan negatif olmayan ağırlıklar seçilir (softmax parametrizasyonu, L-BFGS).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

from mi_ml.metrics import log_loss

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def combine(predictions: list[FloatArray], weights: FloatArray) -> FloatArray:
    stacked = np.stack(predictions)  # (m, n, 3)
    out: FloatArray = np.tensordot(weights, stacked, axes=1)
    return out / out.sum(axis=1, keepdims=True)


def fit_weights(predictions: list[FloatArray], y: IntArray) -> FloatArray:
    m = len(predictions)
    if m == 1:
        return np.ones(1)

    def loss(z: FloatArray) -> float:
        w = np.exp(z - z.max())
        return log_loss(combine(predictions, w / w.sum()), y)

    res = minimize(loss, np.zeros(m), method="L-BFGS-B")
    w = np.exp(res.x - res.x.max())
    weights: FloatArray = w / w.sum()
    return weights
