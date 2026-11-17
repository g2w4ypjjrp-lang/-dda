"""Sızıntısız özellik üretimi."""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta

import pytest

from mi_ml.features import RESULT_DELAY, Match, build_features
from synthetic import league_matches


@pytest.fixture(scope="module")
def matches() -> list[Match]:
    return league_matches(n_teams=8, seasons=2)


def _features(matches: list[Match], target: Match) -> dict[str, float]:
    return build_features(matches, [target])[0].features


def test_future_results_do_not_change_past_features(matches: list[Match]) -> None:
    target = matches[60]
    before = _features(matches, target)
    altered = [
        dataclasses.replace(m, home_goals=9, away_goals=0)
        if m.kickoff_at >= target.kickoff_at
        else m
        for m in matches
    ]
    after = _features(altered, dataclasses.replace(target, home_goals=9, away_goals=0))
    assert before == pytest.approx(after, nan_ok=True)


def test_result_not_known_until_delay(matches: list[Match]) -> None:
    target = matches[60]
    base = _features(matches, target)
    team = target.home
    # Hedeften 2 saat önce başlayan (henüz bitmemiş sayılan) bir maç eklenir: etkisiz olmalı.
    unfinished = Match(target.kickoff_at - timedelta(hours=2), team, "X99", 7, 0, fixture_id=10_000)
    assert _features([*matches, unfinished], target) == pytest.approx(base, nan_ok=True)
    # Sonucu tam zamanında kesinleşen maç: etkili olmalı.
    finished = dataclasses.replace(unfinished, kickoff_at=target.kickoff_at - RESULT_DELAY)
    changed = _features([*matches, finished], target)
    assert changed["h_n"] == base["h_n"] + 1 and changed["h_gf_3"] != base["h_gf_3"]


def test_new_team_has_nan_history(matches: list[Match]) -> None:
    target = Match(
        matches[-1].kickoff_at + timedelta(days=1),
        "Yeni",
        matches[0].away,
        -1,
        -1,
        fixture_id=99_999,
    )
    assert not target.played
    f = _features(matches, target)
    assert f["h_n"] == 0 and math.isnan(f["h_ppg_5"]) and math.isnan(f["h_rest_days"])
    assert f["elo_h"] == 1500.0
    assert f["a_n"] > 0 and not math.isnan(f["a_xgf_5"])


def test_feature_values(matches: list[Match]) -> None:
    rows = build_features(matches)
    assert len(rows) == len(matches)
    first = rows[0].features
    assert first["h_n"] == 0 and first["elo_diff"] == 0
    late = rows[-1].features
    assert 0 <= late["h_ppg_5"] <= 3 and late["h_rest_days"] <= 30
    assert late["d_ppg_5"] == pytest.approx(late["h_ppg_5"] - late["a_ppg_5"])
