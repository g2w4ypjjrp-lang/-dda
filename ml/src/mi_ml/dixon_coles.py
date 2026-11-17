"""Dixon-Coles (1997) skor modeli; ``rho=0`` sabitlenirse bağımsız Poisson modeli.

    λ_ev  = exp(μ + a_ev  + d_dep + γ)
    λ_dep = exp(μ + a_dep + d_ev)
    P(x, y) = τ(x, y; λ, λ', ρ) · Pois(x; λ_ev) · Pois(y; λ_dep)

* Tanımlanabilirlik: Σa = 0, Σd = 0 (son takımın parametresi diğerlerinden türetilir).
* Zaman ağırlığı: w = exp(−ξ · gün); eski maçların etkisi azalır.
* Küçük bir L2 cezası, az maçı olan takımların aşırı uç parametre almasını önler.
* Maksimum olabilirlik, scipy L-BFGS-B ile; ρ ∈ [−0.25, 0.25].

Tahmin yalnızca eğitimde görülen takımlar için yapılır; görülmeyen takımda ``UnknownTeam``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import gammaln

from mi_ml.scores import ScoreMatrix

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class UnknownTeam(KeyError):
    """Takım eğitim verisinde yok; tahmin üretilemez."""


@dataclass(frozen=True)
class MatchRecord:
    kickoff_at: datetime
    home: str
    away: str
    home_goals: int
    away_goals: int


@dataclass
class DixonColes:
    xi: float = 0.0019  # günlük zaman sönümü (yarı ömür ≈ 1 yıl)
    l2: float = 0.01
    fit_rho: bool = True
    teams: list[str] = field(default_factory=list)
    attack: FloatArray = field(default_factory=lambda: np.zeros(0))
    defence: FloatArray = field(default_factory=lambda: np.zeros(0))
    intercept: float = 0.0
    home_adv: float = 0.0
    rho: float = 0.0
    n_matches: int = 0
    converged: bool = False
    log_likelihood: float = float("nan")

    @property
    def name(self) -> str:
        return "dixon_coles" if self.fit_rho else "poisson"

    def _unpack(
        self, theta: FloatArray, n: int
    ) -> tuple[FloatArray, FloatArray, float, float, float]:
        a = np.append(theta[: n - 1], -theta[: n - 1].sum())
        d = np.append(theta[n - 1 : 2 * n - 2], -theta[n - 1 : 2 * n - 2].sum())
        mu, gamma = theta[2 * n - 2], theta[2 * n - 1]
        rho = theta[2 * n] if self.fit_rho else 0.0
        return a, d, float(mu), float(gamma), float(rho)

    def fit(self, matches: Sequence[MatchRecord], *, as_of: datetime | None = None) -> DixonColes:
        if len(matches) < 10:
            raise ValueError("Model için en az 10 maç gerekli")
        teams = sorted({m.home for m in matches} | {m.away for m in matches})
        index = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        hi = np.array([index[m.home] for m in matches])
        ai = np.array([index[m.away] for m in matches])
        x = np.array([m.home_goals for m in matches], dtype=float)
        y = np.array([m.away_goals for m in matches], dtype=float)
        ref = as_of or max(m.kickoff_at for m in matches)
        age = np.array([(ref - m.kickoff_at).total_seconds() / 86400 for m in matches])
        if (age < 0).any():
            raise ValueError("Eğitim verisinde referans zamandan sonraki maç var (sızıntı)")
        w = np.exp(-self.xi * age)
        const = gammaln(x + 1) + gammaln(y + 1)
        low = (x <= 1) & (y <= 1)

        def nll(theta: FloatArray) -> float:
            a, d, mu, gamma, rho = self._unpack(theta, n)
            log_l = mu + a[hi] + d[ai] + gamma
            log_m = mu + a[ai] + d[hi]
            lam, mu_ = np.exp(log_l), np.exp(log_m)
            ll = x * log_l - lam + y * log_m - mu_ - const
            if self.fit_rho:
                tau = np.ones_like(x)
                tau = np.where((x == 0) & (y == 0), 1 - lam * mu_ * rho, tau)
                tau = np.where((x == 0) & (y == 1), 1 + lam * rho, tau)
                tau = np.where((x == 1) & (y == 0), 1 + mu_ * rho, tau)
                tau = np.where((x == 1) & (y == 1), 1 - rho, tau)
                ll = ll + np.where(low, np.log(np.clip(tau, 1e-10, None)), 0.0)
            penalty = 0.5 * self.l2 * (np.sum(a**2) + np.sum(d**2))
            return float(-(w * ll).sum() + penalty)

        size = 2 * n + (1 if self.fit_rho else 0)
        theta0 = np.zeros(size)
        theta0[2 * n - 2] = np.log(
            max(np.average(np.concatenate([x, y]), weights=np.concatenate([w, w])), 0.1)
        )
        theta0[2 * n - 1] = 0.25
        # Takım parametreleri ve μ: ±3 (log ölçek); ev sahibi avantajı γ: ±1.
        bounds: list[tuple[float | None, float | None]] = [(-3.0, 3.0)] * (2 * n - 1)
        bounds.append((-1.0, 1.0))
        if self.fit_rho:
            bounds.append((-0.25, 0.25))
        result = minimize(nll, theta0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 2000})
        a, d, mu, gamma, rho = self._unpack(result.x, n)
        self.teams, self.attack, self.defence = teams, a, d
        self.intercept, self.home_adv, self.rho = mu, gamma, rho
        self.n_matches, self.converged = len(matches), bool(result.success)
        self.log_likelihood = -float(result.fun)
        return self

    def rates(self, home: str, away: str) -> tuple[float, float]:
        index = {t: i for i, t in enumerate(self.teams)}
        missing = [t for t in (home, away) if t not in index]
        if missing:
            raise UnknownTeam(", ".join(missing))
        h, a = index[home], index[away]
        lam = np.exp(self.intercept + self.attack[h] + self.defence[a] + self.home_adv)
        mu = np.exp(self.intercept + self.attack[a] + self.defence[h])
        return float(lam), float(mu)

    def score_matrix(self, home: str, away: str) -> ScoreMatrix:
        lam, mu = self.rates(home, away)
        return ScoreMatrix.from_rates(lam, mu, self.rho)

    def params(self) -> dict[str, object]:
        return {
            "model": self.name,
            "xi": self.xi,
            "l2": self.l2,
            "intercept": self.intercept,
            "home_adv": self.home_adv,
            "rho": self.rho,
            "teams": {
                t: {"attack": float(self.attack[i]), "defence": float(self.defence[i])}
                for i, t in enumerate(self.teams)
            },
            "n_matches": self.n_matches,
            "converged": self.converged,
        }
