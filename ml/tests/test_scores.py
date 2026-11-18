"""Skor matrisi ve piyasaların matematiksel tutarlılığı."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import poisson

from mi_ml.scores import TAU_FLOOR, ScoreMatrix, dc_tau


@pytest.mark.parametrize(
    ("lam", "mu", "rho"), [(1.5, 1.1, 0.0), (2.4, 0.6, -0.1), (0.4, 0.3, 0.1), (3.5, 3.0, -0.05)]
)
def test_markets_are_consistent(lam: float, mu: float, rho: float) -> None:
    m = ScoreMatrix.from_rates(lam, mu, rho)
    assert m.probs.sum() == pytest.approx(1.0)
    assert (m.probs >= 0).all()
    x = m.one_x_two()
    assert sum(x.values()) == pytest.approx(1.0)
    dc = m.double_chance()
    assert dc["1X"] == pytest.approx(x["home"] + x["draw"])
    assert dc["12"] + x["draw"] == pytest.approx(1.0)
    ou = m.over_under()
    for line in ou.values():
        assert line["over"] + line["under"] == pytest.approx(1.0)
    overs = [ou[k]["over"] for k in sorted(ou)]
    assert overs == sorted(overs, reverse=True)  # çizgi yükseldikçe üst olasılığı azalır
    total = m.total_goals_distribution()
    assert sum(total.values()) == pytest.approx(1.0)
    assert ou["2.5"]["under"] == pytest.approx(total["0"] + total["1"] + total["2"])
    btts = m.btts()
    assert btts["no"] == pytest.approx(m.probs[0, :].sum() + m.probs[:, 0].sum() - m.probs[0, 0])
    assert sum(m.team_goals()["home"]) == pytest.approx(1.0)
    top = m.correct_scores(5)
    assert [s["p"] for s in top] == sorted((s["p"] for s in top), reverse=True)


def test_independent_poisson_matches_closed_form() -> None:
    lam, mu = 1.7, 1.2
    m = ScoreMatrix.from_rates(lam, mu, 0.0)
    assert m.probs[2, 1] == pytest.approx(
        poisson.pmf(2, lam) * poisson.pmf(1, mu) / (1 - m.tail_mass)
    )
    # Poisson toplamı: toplam gol ~ Pois(λ+μ)
    assert m.over_under()["2.5"]["under"] == pytest.approx(poisson.cdf(2, lam + mu), abs=1e-6)
    eg = m.expected_goals()
    assert eg["home"] == pytest.approx(lam, abs=1e-4) and eg["away"] == pytest.approx(mu, abs=1e-4)
    assert m.tail_mass < 1e-6


def test_negative_rho_raises_draw_probability() -> None:
    base = ScoreMatrix.from_rates(1.3, 1.1, 0.0).one_x_two()["draw"]
    dc = ScoreMatrix.from_rates(1.3, 1.1, -0.1).one_x_two()["draw"]
    assert dc > base


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="pozitif"):
        ScoreMatrix.from_rates(0.0, 1.0)


@pytest.mark.parametrize(
    ("lam", "mu", "rho"),
    [(3.0, 3.0, 0.25), (5.2, 0.35, -0.25), (0.3, 6.0, -0.2), (4.5, 4.5, 0.1), (8.0, 0.2, -0.25)],
)
def test_rho_is_clamped_for_high_goal_expectations(lam: float, mu: float, rho: float) -> None:
    """Gerçek veride görülen hata: λ yüksekken ligin ρ'su τ'yu negatif yapıyordu (eğitim duruyordu).

    Artık ρ maç başına geçerli aralığa çekilir; olasılıklar geçerli ve piyasalar tutarlı kalır."""
    m = ScoreMatrix.from_rates(lam, mu, rho)
    assert (m.probs >= 0).all() and m.probs.sum() == pytest.approx(1.0)
    assert abs(m.rho) < abs(rho)  # bu maçta küçültüldü ve kayda geçti
    tau = dc_tau(np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1]), np.array(lam), np.array(mu), rho)
    assert (tau >= TAU_FLOOR - 1e-12).all()
    x = m.one_x_two()
    assert x["home"] + x["draw"] + x["away"] == pytest.approx(1.0)


def test_rho_unchanged_for_ordinary_matches() -> None:
    for lam, mu, rho in [(1.5, 1.1, -0.13), (2.4, 0.6, -0.1), (0.4, 0.3, 0.2)]:
        assert ScoreMatrix.from_rates(lam, mu, rho).rho == pytest.approx(rho)


def test_symmetry() -> None:
    m = ScoreMatrix.from_rates(1.2, 1.2, -0.05)
    x = m.one_x_two()
    assert x["home"] == pytest.approx(x["away"])
    assert np.allclose(m.probs, m.probs.T)
