"""Kalibrasyon: çok sınıflı sıcaklık ölçekleme (temperature scaling).

    p_T(k) ∝ p(k)^(1/T)

T > 1 aşırı emin tahminleri yumuşatır, T < 1 keskinleştirir. T yalnızca **doğrulama** dönemindeki
tahminlerle (eğitimde kullanılmayan, test döneminden önceki maçlar) log loss en küçük olacak
şekilde seçilir. Sıralamayı (argmax) değiştirmez.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize_scalar

from mi_ml.metrics import log_loss

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def apply_temperature(probs: FloatArray, temperature: float) -> FloatArray:
    logits = np.log(np.clip(probs, 1e-15, 1.0)) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    out = np.exp(logits)
    result: FloatArray = out / out.sum(axis=1, keepdims=True)
    return result


@dataclass(frozen=True)
class TemperatureScaler:
    temperature: float = 1.0

    @classmethod
    def fit(
        cls, probs: FloatArray, y: IntArray, bounds: tuple[float, float] = (0.25, 4.0)
    ) -> TemperatureScaler:
        if len(y) < 30:
            return cls(1.0)  # az örnekle kalibrasyon güvenilmez; dokunulmaz
        res = minimize_scalar(
            lambda t: log_loss(apply_temperature(probs, t), y), bounds=bounds, method="bounded"
        )
        return cls(float(res.x))

    def transform(self, probs: FloatArray) -> FloatArray:
        return apply_temperature(probs, self.temperature)
