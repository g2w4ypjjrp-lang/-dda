"""İlk yarı modeli: binom inceltmenin tutarlılığı, payın geri bulunması, yayın kapısı."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from mi_ml import halftime
from mi_ml.features import Match
from mi_ml.scores import ScoreMatrix
from synthetic import HT_SHARE, league_matches

FT = ScoreMatrix.from_rates(1.6, 1.1, -0.06).probs[:11, :11]
FT = FT / FT.sum()
SPLIT = (0.45, 0.42)


def test_joint_preserves_full_time_and_is_consistent() -> None:
    t = halftime.joint(FT, SPLIT)
    assert np.allclose(t.sum(axis=(2, 3)), FT)  # MS marjinali değişmez
    assert np.allclose(t.sum(axis=(0, 1)), halftime.ht_matrix(FT, SPLIT))
    i, j, a, b = np.indices(t.shape)
    assert t[(a > i) | (b > j)].sum() == 0  # İY golü MS golünden fazla olamaz

    m = halftime.markets(FT, SPLIT)
    assert sum(m["1x2"].values()) == pytest.approx(1)
    assert sum(m["ht_ft"].values()) == pytest.approx(1)
    for k, code in (("home", "1"), ("draw", "X"), ("away", "2")):
        assert sum(v for key, v in m["ht_ft"].items() if key.startswith(code)) == pytest.approx(
            m["1x2"][k]
        )
    ft_1x2 = ScoreMatrix(FT, 0, 0, 0, 0).one_x_two()
    for k, code in (("home", "1"), ("draw", "X"), ("away", "2")):
        assert sum(v for key, v in m["ht_ft"].items() if key.endswith(code)) == pytest.approx(
            ft_1x2[k]
        )
    assert m["over_under"]["0.5"]["under"] == pytest.approx(halftime.ht_matrix(FT, SPLIT)[0, 0])
    # İY beklenen golü = r × MS beklenen golü (inceltmenin doğrusal özelliği)
    goals = np.arange(11)
    assert m["expected_goals"]["home"] == pytest.approx(SPLIT[0] * (FT.sum(axis=1) * goals).sum())


def test_edge_shares() -> None:
    assert np.allclose(halftime.ht_matrix(FT, (1.0, 1.0)), FT)
    zero = halftime.ht_matrix(FT, (0.0, 0.0))
    assert zero[0, 0] == pytest.approx(1)


def test_fit_split_recovers_share_and_ignores_missing() -> None:
    matches = league_matches(n_teams=12, seasons=6)
    split = halftime.fit_split(matches)
    assert split is not None
    assert split.home == pytest.approx(HT_SHARE[0], abs=0.03)
    assert split.away == pytest.approx(HT_SHARE[1], abs=0.03)
    blank = [dataclasses.replace(m, ht_home=None, ht_away=None) for m in matches]
    assert halftime.fit_split(blank) is None


def test_evaluation_gate() -> None:
    # Doğru kurulmuş veride bile ~150 test maçında ECE gürültülüdür ve kapı çekimser kalır;
    # 12 sezonluk sentetik lig (≈300 test maçı) yeterli örneklem verir.
    matches = league_matches(n_teams=12, seasons=12)
    test_from = matches[int(len(matches) * 0.8)].kickoff_at
    ok = halftime.evaluate(matches, test_from, window_days=60)
    assert ok["available"] is True, ok["reasons"]
    t = ok["test"]
    assert t["n"] >= 100 and t["log_loss"] < t["baseline_log_loss"]
    assert t["ht_ft_log_loss"] < t["ht_ft_baseline_log_loss"]

    # İY skoru çoğunlukla eksikse yayımlanmaz ve nedeni yazılır.
    sparse: list[Match] = [
        m if i % 3 == 0 else dataclasses.replace(m, ht_home=None, ht_away=None)
        for i, m in enumerate(matches)
    ]
    bad = halftime.evaluate(sparse, test_from, window_days=60)
    assert bad["available"] is False
    assert any("kapsam" in r for r in bad["reasons"])

    # Küçük test örneklemi: çekimser.
    small = halftime.evaluate(matches, matches[-40].kickoff_at, window_days=60)
    assert small["available"] is False and any("örneklem" in r for r in small["reasons"])


def test_prediction_payload_follows_gate() -> None:
    from types import SimpleNamespace

    from mi_ml.predict import first_half_payload

    matrix = ScoreMatrix(FT, 1.6, 1.1, -0.06, 0.0)
    none = first_half_payload(SimpleNamespace(first_half=None), matrix)  # type: ignore[arg-type]
    assert none["available"] is False and none["reasons"]
    closed = {"available": False, "split": {"home": 0.45, "away": 0.42}, "reasons": ["x"]}
    assert first_half_payload(SimpleNamespace(first_half=closed), matrix)["reasons"] == ["x"]  # type: ignore[arg-type]
    ok = {
        "available": True,
        "split": {"home": 0.45, "away": 0.42},
        "reasons": [],
        "test": {"n": 300, "log_loss": 1.0, "baseline_log_loss": 1.05, "ece": 0.02},
    }
    out = first_half_payload(SimpleNamespace(first_half=ok), matrix)  # type: ignore[arg-type]
    assert out["available"] is True and out["split"] == {"home": 0.45, "away": 0.42}
    assert out["test"]["n"] == 300 and set(out["ht_ft"]) == set(halftime.HTFT)
