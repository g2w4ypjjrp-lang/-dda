"""Dixon-Coles / Poisson parametre geri kazanımı, Elo, Monte Carlo, metrikler, kalibrasyon, ensemble."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from mi_ml import montecarlo
from mi_ml.calibration import TemperatureScaler, apply_temperature
from mi_ml.dixon_coles import DixonColes, MatchRecord, UnknownTeam
from mi_ml.elo import Elo, goal_multiplier
from mi_ml.ensemble import combine, fit_weights
from mi_ml.metrics import brier, ece, evaluate, log_loss, outcome_label
from mi_ml.scores import ScoreMatrix
from synthetic import league


@pytest.fixture(scope="module")
def synthetic() -> tuple[list[MatchRecord], dict[str, tuple[float, float]]]:
    return league(n_teams=12, seasons=6)


def test_dixon_coles_recovers_parameters(
    synthetic: tuple[list[MatchRecord], dict[str, tuple[float, float]]],
) -> None:
    matches, truth = synthetic
    model = DixonColes(xi=0.0, l2=0.0).fit(matches)
    assert model.converged
    assert model.home_adv == pytest.approx(0.28, abs=0.06)
    assert model.intercept == pytest.approx(0.15, abs=0.06)
    assert model.rho == pytest.approx(-0.08, abs=0.07)
    est = np.array([model.attack[model.teams.index(t)] for t in sorted(truth)])
    true = np.array([truth[t][0] for t in sorted(truth)])
    assert np.corrcoef(est, true)[0, 1] > 0.9
    assert np.abs(est - true).max() < 0.2


def test_poisson_variant_and_prediction(
    synthetic: tuple[list[MatchRecord], dict[str, tuple[float, float]]],
) -> None:
    matches, _ = synthetic
    model = DixonColes(fit_rho=False).fit(matches)
    assert model.name == "poisson" and model.rho == 0.0
    lam, mu = model.rates("T00", "T01")
    assert lam > 0 and mu > 0
    assert model.score_matrix("T00", "T01").probs.sum() == pytest.approx(1.0)
    with pytest.raises(UnknownTeam):
        model.rates("T00", "Bilinmeyen")
    params = model.params()
    assert set(params["teams"]) == {f"T{i:02d}" for i in range(12)}  # type: ignore[arg-type]


def test_dixon_coles_rejects_future_matches(
    synthetic: tuple[list[MatchRecord], dict[str, tuple[float, float]]],
) -> None:
    matches, _ = synthetic
    with pytest.raises(ValueError, match="sızıntı"):
        DixonColes().fit(matches, as_of=matches[0].kickoff_at)
    with pytest.raises(ValueError, match="en az"):
        DixonColes().fit(matches[:5])


def test_time_decay_downweights_old_form() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    old = [MatchRecord(t0 + timedelta(days=i), "A", "B", 4, 0) for i in range(20)]
    recent = [MatchRecord(t0 + timedelta(days=700 + i), "B", "A", 4, 0) for i in range(20)]
    data = old + recent
    flat = DixonColes(xi=0.0, fit_rho=False).fit(data)
    decayed = DixonColes(xi=0.01, fit_rho=False).fit(data)
    att = lambda m, t: m.attack[m.teams.index(t)]  # noqa: E731
    assert att(decayed, "B") - att(decayed, "A") > att(flat, "B") - att(flat, "A")


def test_elo() -> None:
    assert goal_multiplier(0) == 1.0 and goal_multiplier(2) == 1.5 and goal_multiplier(5) == 2.0
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    elo = Elo()
    before = elo.run(
        [MatchRecord(t0, "A", "B", 3, 0), MatchRecord(t0 + timedelta(days=7), "B", "A", 0, 0)]
    )
    assert before[0] == (1500.0, 1500.0)  # maç öncesi değerler
    assert elo.rating("A") > 1500 > elo.rating("B")
    assert elo.rating("A") + elo.rating("B") == pytest.approx(3000.0)  # sıfır toplamlı
    assert 0.5 < elo.expected_home("A", "A") < 1.0  # ev sahibi avantajı


def test_monte_carlo_converges_and_is_reproducible() -> None:
    m = ScoreMatrix.from_rates(1.6, 1.1, -0.06)
    exact = m.over_under()["2.5"]["over"]

    def over(h: np.ndarray, a: np.ndarray) -> np.ndarray:
        return (h + a) > 2.5

    estimates = montecarlo.convergence(m, over)
    assert [e.n for e in estimates] == [10_000, 50_000, 100_000]
    assert montecarlo.converged(estimates)
    for e in estimates:
        assert abs(e.p - exact) < 4 * e.std_error + 1e-9
    assert montecarlo.estimate(m, over, 10_000, seed=42) == montecarlo.estimate(
        m, over, 10_000, seed=42
    )


def test_metrics_known_values() -> None:
    y = np.array([0, 1, 2, 0])
    perfect = np.eye(3)[y]
    assert brier(perfect, y) == pytest.approx(0.0)
    uniform = np.full((4, 3), 1 / 3)
    assert brier(uniform, y) == pytest.approx(2 / 3)
    assert log_loss(uniform, y) == pytest.approx(np.log(3))
    report = evaluate(uniform, y)
    assert report["n"] == 4 and report["confusion_matrix"][0][0] == 2
    assert outcome_label(2, 1) == 0 and outcome_label(1, 1) == 1 and outcome_label(0, 3) == 2
    with pytest.raises(ValueError, match="toplamı"):
        brier(np.full((4, 3), 0.5), y)


def test_ece_detects_overconfidence() -> None:
    rng = np.random.default_rng(0)
    n = 5000
    true = rng.dirichlet([3, 2, 3], n)
    y = np.array([rng.choice(3, p=p) for p in true])
    assert ece(true, y) < 0.03
    sharp = apply_temperature(true, 0.4)  # aşırı emin
    assert ece(sharp, y) > 0.08
    scaler = TemperatureScaler.fit(sharp, y)
    assert scaler.temperature == pytest.approx(2.5, rel=0.2)
    assert ece(scaler.transform(sharp), y) < 0.03
    assert (scaler.transform(sharp).argmax(1) == sharp.argmax(1)).all()  # sıralama değişmez
    assert TemperatureScaler.fit(sharp[:10], y[:10]).temperature == 1.0


def test_ensemble_weights_prefer_better_model() -> None:
    rng = np.random.default_rng(1)
    n = 3000
    true = rng.dirichlet([3, 2, 3], n)
    y = np.array([rng.choice(3, p=p) for p in true])
    noise = rng.dirichlet([1, 1, 1], n)
    good, bad = true, 0.3 * true + 0.7 * noise
    w = fit_weights([good, bad], y)
    assert w.sum() == pytest.approx(1.0) and (w >= 0).all()
    assert w[0] > 0.8
    assert log_loss(combine([good, bad], w), y) <= log_loss(bad, y)


def test_dixon_coles_handles_lopsided_matchups() -> None:
    """Gerçek veride (Şampiyonlar Ligi, güçlü–zayıf eşleşmeler) λ ≈ 5–7 olur; ligin ρ'su bu
    maçlarda τ'yu negatif yapıyor ve eğitim "rho … geçersiz" hatasıyla duruyordu."""
    rng = np.random.default_rng(3)
    t0 = datetime(2023, 8, 1, tzinfo=UTC)
    strength = {"Dev": 1.4, "Orta": 0.2, "Zayıf1": -0.9, "Zayıf2": -1.0, "Zayıf3": -0.8}
    teams = sorted(strength)
    matches = []
    for k in range(6):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                lam = np.exp(0.2 + strength[h] - strength[a] + 0.3)
                mu = np.exp(0.2 + strength[a] - strength[h])
                when = t0 + timedelta(days=7 * len(matches) // 4 + k)
                matches.append(MatchRecord(when, h, a, int(rng.poisson(lam)), int(rng.poisson(mu))))
    model = DixonColes(xi=0.0).fit(matches)
    lam, _ = model.rates("Dev", "Zayıf2")
    assert lam > 4.5  # senaryo gerçekten uç gol beklentisi içeriyor
    # Gerçek liglerde ρ çoğunlukla negatiftir; sunucudaki hatayı veren durum ρ = −0,2 civarı.
    for rho in (model.rho, -0.2, 0.2):
        model.rho = rho
        clamped = 0
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                m = model.score_matrix(h, a)
                assert (m.probs >= 0).all() and m.probs.sum() == pytest.approx(1.0)
                assert sum(m.one_x_two().values()) == pytest.approx(1.0)
                clamped += abs(m.rho) < abs(rho) - 1e-12
        if rho == -0.2:
            assert clamped > 0  # eski kod bu eşleşmelerde ValueError verirdi
