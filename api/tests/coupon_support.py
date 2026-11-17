"""Kupon ve sanal portföy testleri için ortak veri: lig, takımlar, maçlar, model sürümü, tahminler."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from conftest import Clock

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)  # Türkiye 12:00


def poisson_matrix(lam: float, mu: float) -> list[list[float]]:
    ph = [math.exp(-lam) * lam**k / math.factorial(k) for k in range(11)]
    pa = [math.exp(-mu) * mu**k / math.factorial(k) for k in range(11)]
    m = [[x * y for y in pa] for x in ph]
    t = sum(map(sum, m))
    return [[v / t for v in r] for r in m]


def markets(lam: float, mu: float) -> dict[str, Any]:
    m = poisson_matrix(lam, mu)
    cells = [(i, j, m[i][j]) for i in range(11) for j in range(11)]
    home = sum(p for i, j, p in cells if i > j)
    draw = sum(p for i, j, p in cells if i == j)
    over = {
        f"{line}": {"over": sum(p for i, j, p in cells if i + j > line)} for line in (1.5, 2.5, 3.5)
    }
    for v in over.values():
        v["under"] = 1 - v["over"]
    btts = sum(p for i, j, p in cells if i > 0 and j > 0)
    return {
        "score_matrix": m,
        "1x2": {"home": home, "draw": draw, "away": 1 - home - draw},
        "double_chance": {"1X": home + draw, "12": 1 - draw, "X2": 1 - home},
        "over_under": over,
        "btts": {"yes": btts, "no": 1 - btts},
    }


def pois(lam: float, k: int) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def first_half(lam: float, mu: float, r: tuple[float, float] = (0.45, 0.42)) -> dict[str, Any]:
    """Bağımsız türetme: Poisson golün inceltilmesi = iki bağımsız yarı Poisson'u. İY ~ Pois(rλ),
    ikinci yarı ~ Pois((1−r)λ). Motorun binom inceltme hesabını bununla karşılaştırırız."""
    g = 10
    ht = [[pois(r[0] * lam, x) * pois(r[1] * mu, y) for y in range(g + 1)] for x in range(g + 1)]
    sh = [
        [pois((1 - r[0]) * lam, u) * pois((1 - r[1]) * mu, v) for v in range(g + 1)]
        for u in range(g + 1)
    ]
    res = lambda x, y: "1" if x > y else "X" if x == y else "2"  # noqa: E731
    htft: dict[str, float] = {}
    for x in range(g + 1):
        for y in range(g + 1):
            for u in range(g + 1 - x):
                for v in range(g + 1 - y):
                    key = f"{res(x, y)}/{res(x + u, y + v)}"
                    htft[key] = htft.get(key, 0.0) + ht[x][y] * sh[u][v]
    home = sum(ht[x][y] for x in range(g + 1) for y in range(g + 1) if x > y)
    draw = sum(ht[x][x] for x in range(g + 1))
    zero = ht[0][0]
    one = zero + ht[1][0] + ht[0][1]
    return {
        "available": True,
        "split": {"home": r[0], "away": r[1]},
        "1x2": {"home": home, "draw": draw, "away": 1 - home - draw},
        "over_under": {
            "0.5": {"over": 1 - zero, "under": zero},
            "1.5": {"over": 1 - one, "under": one},
        },
        "ht_ft": htft,
    }


def seed(sql: psycopg.Connection[Any], clock: Clock) -> dict[str, Any]:
    clock.now = NOW
    comp = sql.execute(
        "INSERT INTO football_competitions (provider, external_id, name, fetched_at) VALUES ('test','1','Test Ligi',%s) RETURNING id",
        (NOW,),
    ).fetchone()[0]
    season = sql.execute(
        "INSERT INTO football_seasons (competition_id, year, label) VALUES (%s, 2026, '2026/27') RETURNING id",
        (comp,),
    ).fetchone()[0]
    teams = [
        sql.execute(
            "INSERT INTO football_teams (provider, external_id, name, fetched_at) VALUES ('test',%s,%s,%s) RETURNING id",
            (str(i), f"Takım {i}", NOW),
        ).fetchone()[0]
        for i in range(8)
    ]
    version = sql.execute(
        "INSERT INTO ml_model_versions (scope_key, scope, status, trained_until, seed, config, components, temperature, metrics,"
        " data_fingerprint, n_rows, artifact) VALUES ('competition:1','{}','champion',%s,42,'{}','{}',1,'{}',%s,500,'{}') RETURNING id",
        (NOW - timedelta(days=1), "a" * 64),
    ).fetchone()[0]
    rates = [(2.4, 0.5), (1.3, 1.2), (0.7, 2.0), (1.6, 1.0)]
    fixtures, preds = [], []
    for k, (lam, mu) in enumerate(rates):
        kickoff = NOW + timedelta(hours=3 + k)
        fx = sql.execute(
            "INSERT INTO football_fixtures (provider, external_id, season_id, kickoff_at, status, home_team_id, away_team_id, fetched_at)"
            " VALUES ('test', %s, %s, %s, 'scheduled', %s, %s, %s) RETURNING id",
            (str(k), season, kickoff, teams[2 * k], teams[2 * k + 1], NOW),
        ).fetchone()[0]
        pred = sql.execute(
            "INSERT INTO ml_predictions (fixture_id, model_version_id, created_at, kickoff_at, status, probabilities, reliability,"
            " features, feature_hash, data_snapshot) VALUES (%s,%s,%s,%s,'published',%s,'medium','{}',%s,'{}') RETURNING id",
            (
                fx,
                version,
                NOW - timedelta(hours=1),
                kickoff,
                json.dumps(
                    {**markets(lam, mu), "first_half": first_half(lam, mu)}
                    if k != 3
                    else {
                        **markets(lam, mu),
                        "first_half": {"available": False, "reasons": ["test"]},
                    }
                ),
                "b" * 64,
            ),
        ).fetchone()[0]
        fixtures.append(fx)
        preds.append(pred)
    return {"fixtures": fixtures, "preds": preds, "version": version}
