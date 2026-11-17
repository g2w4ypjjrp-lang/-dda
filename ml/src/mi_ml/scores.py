"""Skor olasılık matrisi ve ondan türetilen piyasalar.

Tüm piyasalar (1X2, çifte şans, alt/üst, karşılıklı gol, doğru skor, gol dağılımı) **aynı ortak
skor dağılımından** türetilir. Böylece ilişkili piyasalar birbiriyle tutarlıdır: ör. P(1) + P(X)
+ P(2) = 1, P(Ü2.5) = 1 − P(A2.5), P(1X) = P(1) + P(X); bağımsızmış gibi ayrı ayrı tahmin edilmez.

Matris ``M[i, j] = P(ev sahibi i gol, deplasman j gol)``; ``0..max_goals`` aralığı tutulur.
Dışarıda kalan kuyruk olasılığı ``tail_mass`` olarak raporlanır ve matris 1'e normalize edilir
(λ ≤ 4 için kuyruk < 1e-5, ``max_goals=12``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import poisson

FloatArray = NDArray[np.float64]
MAX_GOALS = 12
TOTAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)


def dc_tau(
    x: NDArray[Any], y: NDArray[Any], lam: NDArray[Any], mu: NDArray[Any], rho: float
) -> FloatArray:
    """Dixon-Coles düşük skor düzeltmesi τ(x, y). (0,0), (0,1), (1,0), (1,1) dışındaki skorlarda 1."""
    tau = np.ones(np.broadcast(x, y, lam, mu).shape)
    tau = np.where((x == 0) & (y == 0), 1.0 - lam * mu * rho, tau)
    tau = np.where((x == 0) & (y == 1), 1.0 + lam * rho, tau)
    tau = np.where((x == 1) & (y == 0), 1.0 + mu * rho, tau)
    tau = np.where((x == 1) & (y == 1), 1.0 - rho, tau)
    return tau


@dataclass(frozen=True)
class ScoreMatrix:
    probs: FloatArray  # (G+1, G+1), toplamı 1
    lambda_home: float
    lambda_away: float
    rho: float
    tail_mass: float

    @classmethod
    def from_rates(
        cls, lambda_home: float, lambda_away: float, rho: float = 0.0, max_goals: int = MAX_GOALS
    ) -> ScoreMatrix:
        if lambda_home <= 0 or lambda_away <= 0:
            raise ValueError("Gol beklentileri pozitif olmalı")
        goals = np.arange(max_goals + 1)
        ph = poisson.pmf(goals, lambda_home)
        pa = poisson.pmf(goals, lambda_away)
        grid = np.outer(ph, pa)
        x, y = np.meshgrid(goals, goals, indexing="ij")
        grid = grid * dc_tau(x, y, np.array(lambda_home), np.array(lambda_away), rho)
        if (grid < 0).any():
            raise ValueError("rho bu gol beklentileriyle geçersiz (negatif olasılık)")
        captured = float(grid.sum())
        return cls(
            grid / captured,
            float(lambda_home),
            float(lambda_away),
            float(rho),
            max(0.0, 1 - captured),
        )

    # --- Piyasalar ------------------------------------------------------------------------------

    def one_x_two(self) -> dict[str, float]:
        p = self.probs
        home = float(np.tril(p, -1).sum())
        draw = float(np.trace(p))
        return {"home": home, "draw": draw, "away": float(1.0 - home - draw)}

    def double_chance(self) -> dict[str, float]:
        m = self.one_x_two()
        return {
            "1X": m["home"] + m["draw"],
            "12": m["home"] + m["away"],
            "X2": m["draw"] + m["away"],
        }

    def total_goals_distribution(self, cap: int = 6) -> dict[str, float]:
        g = self.probs.shape[0]
        totals = np.add.outer(np.arange(g), np.arange(g))
        dist = {str(k): float(self.probs[totals == k].sum()) for k in range(cap)}
        dist[f"{cap}+"] = float(self.probs[totals >= cap].sum())
        return dist

    def over_under(self, lines: tuple[float, ...] = TOTAL_LINES) -> dict[str, dict[str, float]]:
        g = self.probs.shape[0]
        totals = np.add.outer(np.arange(g), np.arange(g))
        out = {}
        for line in lines:
            over = float(self.probs[totals > line].sum())
            out[f"{line:.1f}"] = {"over": over, "under": 1.0 - over}
        return out

    def btts(self) -> dict[str, float]:
        yes = float(self.probs[1:, 1:].sum())
        return {"yes": yes, "no": 1.0 - yes}

    def team_goals(self) -> dict[str, list[float]]:
        return {
            "home": [float(v) for v in self.probs.sum(axis=1)],
            "away": [float(v) for v in self.probs.sum(axis=0)],
        }

    def correct_scores(self, top: int = 10) -> list[dict[str, Any]]:
        flat = np.argsort(self.probs, axis=None)[::-1][:top]
        rows, cols = np.unravel_index(flat, self.probs.shape)
        return [
            {"home": int(r), "away": int(c), "p": float(self.probs[r, c])}
            for r, c in zip(rows, cols, strict=True)
        ]

    def expected_goals(self) -> dict[str, float]:
        goals = np.arange(self.probs.shape[0])
        return {
            "home": float((self.probs.sum(axis=1) * goals).sum()),
            "away": float((self.probs.sum(axis=0) * goals).sum()),
        }

    def markets(self) -> dict[str, Any]:
        return {
            "1x2": self.one_x_two(),
            "double_chance": self.double_chance(),
            "over_under": self.over_under(),
            "btts": self.btts(),
            "total_goals": self.total_goals_distribution(),
            "correct_score": self.correct_scores(),
            "expected_goals": self.expected_goals(),
        }
