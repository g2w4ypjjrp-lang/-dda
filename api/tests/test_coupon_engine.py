"""Kupon motoru: ortak olasılık matematiği, Monte Carlo doğrulaması, profiller (veritabanı yok)."""

from __future__ import annotations

import math

import pytest

from mi_api.coupons.engine import (
    Candidate,
    CouponError,
    Leg,
    build,
    evaluate,
    fixture_joint,
    joint_probability,
    market,
    risk_text,
    simulate,
)


def poisson_matrix(lam: float, mu: float, g: int = 10) -> list[list[float]]:
    ph = [math.exp(-lam) * lam**k / math.factorial(k) for k in range(g + 1)]
    pa = [math.exp(-mu) * mu**k / math.factorial(k) for k in range(g + 1)]
    m = [[x * y for y in pa] for x in ph]
    total = sum(map(sum, m))
    return [[v / total for v in row] for row in m]


def probs(lam: float, mu: float) -> dict[str, object]:
    m = poisson_matrix(lam, mu)
    home = sum(m[i][j] for i in range(11) for j in range(11) if i > j)
    draw = sum(m[i][i] for i in range(11))
    return {"score_matrix": m, "1x2": {"home": home, "draw": draw, "away": 1 - home - draw}}


def test_same_match_legs_use_joint_distribution() -> None:
    p = probs(1.8, 0.9)
    m = p["score_matrix"]
    home, over = market("1x2", "home"), market("total", "over_2.5")
    joint = fixture_joint([Leg(1, home, p), Leg(1, over, p)])
    manual = sum(m[i][j] for i in range(11) for j in range(11) if i > j and i + j > 2)  # type: ignore[index]
    assert joint == pytest.approx(manual)
    naive = fixture_joint([Leg(1, home, p)]) * fixture_joint([Leg(1, over, p)])
    assert joint != pytest.approx(naive, abs=1e-3)  # bağımsız sayılsaydı yanlış olurdu
    # Çelişen seçimler: 1 ve 2 aynı anda olamaz.
    assert fixture_joint([Leg(1, home, p), Leg(1, market("1x2", "away"), p)]) == 0.0


def test_markets_partition_and_complement() -> None:
    p = probs(1.4, 1.2)
    one = lambda c, k: fixture_joint([Leg(1, market(c, k), p)])  # noqa: E731
    assert one("1x2", "home") + one("1x2", "draw") + one("1x2", "away") == pytest.approx(1.0)
    assert one("double_chance", "1X") == pytest.approx(one("1x2", "home") + one("1x2", "draw"))
    assert one("total", "over_2.5") + one("total", "under_2.5") == pytest.approx(1.0)
    assert one("btts", "yes") + one("btts", "no") == pytest.approx(1.0)


def test_different_matches_multiply_and_monte_carlo_agrees() -> None:
    legs = [
        Leg(1, market("1x2", "home"), probs(1.9, 0.8)),
        Leg(2, market("total", "over_1.5"), probs(1.5, 1.3)),
        Leg(2, market("btts", "yes"), probs(1.5, 1.3)),
        Leg(3, market("double_chance", "X2"), probs(1.1, 1.2)),
    ]
    exact = joint_probability(legs)
    expected = fixture_joint(legs[:1]) * fixture_joint(legs[1:3]) * fixture_joint(legs[3:])
    assert exact == pytest.approx(expected)
    ev = evaluate(legs)
    assert ev.converged
    assert [s.n for s in ev.simulations] == [10_000, 50_000]
    for s in ev.simulations:
        assert abs(s.p - exact) < 4 * s.std_error
    assert simulate(legs, 10_000, seed=42) == simulate(legs, 10_000, seed=42)  # tekrar üretilebilir
    d = ev.as_dict()
    assert d["one_in"] == pytest.approx(1 / exact, abs=0.1)


def test_fallback_without_matrix() -> None:
    old = {
        "1x2": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "over_under": {"2.5": {"over": 0.4, "under": 0.6}},
    }
    assert fixture_joint([Leg(1, market("total", "under_2.5"), old)]) == 0.6
    with pytest.raises(CouponError) as err:
        fixture_joint(
            [Leg(1, market("1x2", "home"), old), Leg(1, market("total", "over_2.5"), old)]
        )
    assert err.value.code == "joint_unavailable"
    assert simulate([Leg(1, market("1x2", "home"), old)], 20_000).p == pytest.approx(0.5, abs=0.02)


def test_unknown_market_and_empty() -> None:
    with pytest.raises(CouponError):
        market("1x2", "maybe")
    with pytest.raises(CouponError):
        joint_probability([])


def _cands() -> list[Candidate]:
    return [
        Candidate(1, 101, probs(2.4, 0.5), "high"),
        Candidate(2, 102, probs(1.3, 1.2), "medium"),
        Candidate(3, 103, probs(0.7, 2.0), "medium"),
        Candidate(4, 104, probs(1.5, 1.5), "low"),
    ]


def test_profiles_respect_probability_bands_and_reliability() -> None:
    low = build(_cands(), profile="low", size=2)
    assert len({p.candidate.fixture_id for p in low}) == 2  # maç başına tek seçim
    assert all(p.probability >= 0.70 for p in low)
    assert all(p.candidate.reliability != "low" for p in low)
    high = build(_cands(), profile="high", size=3)
    assert all(0.38 <= p.probability <= 0.62 for p in high)
    only_totals = build(_cands(), profile="low", size=1, markets=frozenset({"total"}))
    assert only_totals[0].market.code == "total"
    with pytest.raises(CouponError) as err:
        build(_cands(), profile="low", size=4)
    assert err.value.code == "insufficient_candidates"


def test_risk_text() -> None:
    text = risk_text(0.25, 3, "medium")
    assert "%25.0" in text and "4.0" in text and "orta" in text and "kesin sonuç değildir" in text
