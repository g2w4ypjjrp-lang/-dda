"""Yalnızca testler için: bilinen parametrelerden üretilmiş sentetik lig.

Gerçek veri değildir; modelin parametreleri geri bulabildiğini ve hattın uçtan uca çalıştığını
doğrulamak için kullanılır. Uygulamada gösterilmez.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from mi_ml.dixon_coles import MatchRecord
from mi_ml.features import Match
from mi_ml.scores import ScoreMatrix


def true_params(n_teams: int, seed: int = 7) -> dict[str, tuple[float, float]]:
    rng = np.random.default_rng(seed)
    attack = rng.normal(0, 0.3, n_teams)
    defence = rng.normal(0, 0.25, n_teams)
    attack -= attack.mean()
    defence -= defence.mean()
    return {f"T{i:02d}": (float(attack[i]), float(defence[i])) for i in range(n_teams)}


def league(
    n_teams: int = 12,
    seasons: int = 3,
    *,
    intercept: float = 0.15,
    home_adv: float = 0.28,
    rho: float = -0.08,
    seed: int = 11,
    start: datetime = datetime(2023, 8, 1, 18, 0, tzinfo=UTC),
    spacing_hours: int = 6,
) -> tuple[list[MatchRecord], dict[str, tuple[float, float]]]:
    params = true_params(n_teams)
    teams = sorted(params)
    rng = np.random.default_rng(seed)
    matches: list[MatchRecord] = []
    when = start
    for _ in range(seasons):
        pairs = [(h, a) for h in teams for a in teams if h != a]
        rng.shuffle(pairs)
        for i, (h, a) in enumerate(pairs):
            lam = np.exp(intercept + params[h][0] + params[a][1] + home_adv)
            mu = np.exp(intercept + params[a][0] + params[h][1])
            m = ScoreMatrix.from_rates(float(lam), float(mu), rho)
            idx = rng.choice(m.probs.size, p=m.probs.ravel())
            x, y = np.unravel_index(idx, m.probs.shape)
            matches.append(
                MatchRecord(when + timedelta(hours=spacing_hours * i), h, a, int(x), int(y))
            )
        when += timedelta(days=365)
    return matches, params


HT_SHARE = (0.45, 0.42)  # sentetik İY gol payı (ev, deplasman)


def league_matches(n_teams: int = 12, seasons: int = 4, seed: int = 11) -> list[Match]:
    """Model hattı testleri için: gerçekçi aralıklı (2 günde bir maç) sentetik lig, sentetik xG ve
    İY skoruyla (her gol bağımsız olarak ``HT_SHARE`` olasılıkla ilk yarıda)."""
    records, _ = league(n_teams, seasons, seed=seed, spacing_hours=48)
    rng = np.random.default_rng(seed + 1)
    ht = np.random.default_rng(seed + 2)
    return [
        Match(
            r.kickoff_at,
            r.home,
            r.away,
            r.home_goals,
            r.away_goals,
            fixture_id=i + 1,
            competition_id=1,
            xg_home=round(max(0.05, r.home_goals + rng.normal(0, 0.6)), 2),
            xg_away=round(max(0.05, r.away_goals + rng.normal(0, 0.6)), 2),
            ht_home=int(ht.binomial(r.home_goals, HT_SHARE[0])),
            ht_away=int(ht.binomial(r.away_goals, HT_SHARE[1])),
        )
        for i, r in enumerate(records)
    ]
