"""Monte Carlo simülasyonu ve yakınsama denetimi.

Tek maç piyasaları skor matrisinden **kesin** hesaplanır; simülasyon, birleşik olaylar (kupon,
sanal portföy) için kullanılır. Bu modül, simülasyonun kesin değere yakınsadığını ve tekrar
üretilebilir olduğunu (sabit tohum) doğrulamak için de kullanılır.

Not: simülasyon sayısını artırmak yalnızca **örnekleme hatasını** azaltır; modelin doğruluğunu
artırmaz.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mi_ml.scores import ScoreMatrix

IntArray = NDArray[np.int64]
DEFAULT_SEED = 42
SIZES = (10_000, 50_000, 100_000)


def sample_scores(
    matrix: ScoreMatrix, n: int, rng: np.random.Generator
) -> tuple[IntArray, IntArray]:
    flat = matrix.probs.ravel()
    idx = rng.choice(flat.size, size=n, p=flat / flat.sum())
    home, away = np.unravel_index(idx, matrix.probs.shape)
    return home.astype(np.int64), away.astype(np.int64)


@dataclass(frozen=True)
class Estimate:
    n: int
    p: float
    std_error: float


def estimate(
    matrix: ScoreMatrix,
    event: Callable[[IntArray, IntArray], NDArray[np.bool_]],
    n: int,
    seed: int = DEFAULT_SEED,
) -> Estimate:
    home, away = sample_scores(matrix, n, np.random.default_rng(seed))
    hits = event(home, away)
    p = float(hits.mean())
    return Estimate(n, p, float(np.sqrt(max(p * (1 - p), 1e-12) / n)))


def convergence(
    matrix: ScoreMatrix,
    event: Callable[[IntArray, IntArray], NDArray[np.bool_]],
    sizes: tuple[int, ...] = SIZES,
    seed: int = DEFAULT_SEED,
) -> list[Estimate]:
    """Artan örnek sayılarıyla tahminler; ardışık farkların standart hata içinde kalması beklenir."""
    return [estimate(matrix, event, n, seed + i) for i, n in enumerate(sizes)]


def converged(estimates: list[Estimate], z: float = 4.0) -> bool:
    last = estimates[-1]
    return all(abs(e.p - last.p) <= z * np.hypot(e.std_error, last.std_error) for e in estimates)
