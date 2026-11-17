"""Zaman noktasında (point-in-time) özellik üretimi.

**Sızıntı kuralı:** bir maçın özellikleri yalnızca sonucu o maçın başlama saatinden önce
**kesinleşmiş** maçlardan hesaplanır. Bir maçın sonucu, başlama saatinden ``RESULT_DELAY``
(150 dk) sonra bilinir kabul edilir. Böylece aynı gün oynanan, henüz bitmemiş maçlar da dışarıda
kalır. ``test_features.py`` gelecekteki sonuçları değiştirmenin geçmiş özellikleri
değiştirmediğini doğrular.

Eksik veri NaN olarak bırakılır (ör. xG vermeyen sağlayıcı); uydurulmaz. LightGBM NaN'ı doğal
işler; doğrusal model eğitimde medyanla doldurur.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from numpy.typing import NDArray

from mi_ml.dixon_coles import MatchRecord
from mi_ml.elo import Elo

RESULT_DELAY = timedelta(minutes=150)
WINDOWS = (3, 5, 10, 20)
NAN = float("nan")


@dataclass(frozen=True)
class Match(MatchRecord):
    """Model girdisi olan maç. Sonucu bilinmeyen (gelecek) maçta goller -1'dir."""

    fixture_id: int = 0
    competition_id: int = 0
    xg_home: float | None = None
    xg_away: float | None = None
    ht_home: int | None = None  # ilk yarı skoru (sağlayıcı verdiyse)
    ht_away: int | None = None

    @property
    def played(self) -> bool:
        return self.home_goals >= 0 and self.away_goals >= 0


@dataclass
class _TeamGame:
    kickoff_at: datetime
    home: bool
    gf: int
    ga: int
    xgf: float | None
    xga: float | None
    opp_elo: float

    @property
    def points(self) -> int:
        return 3 if self.gf > self.ga else 1 if self.gf == self.ga else 0


def _mean(values: list[float]) -> float:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return float(np.mean(clean)) if clean else NAN


@dataclass
class FeatureBuilder:
    elo: Elo = field(default_factory=Elo)
    history: dict[str, deque[_TeamGame]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=40))
    )

    def _release(self, match: Match) -> None:
        pre_home, pre_away = self.elo.update(match)
        self.history[match.home].append(
            _TeamGame(
                match.kickoff_at,
                True,
                match.home_goals,
                match.away_goals,
                match.xg_home,
                match.xg_away,
                pre_away,
            )
        )
        self.history[match.away].append(
            _TeamGame(
                match.kickoff_at,
                False,
                match.away_goals,
                match.home_goals,
                match.xg_away,
                match.xg_home,
                pre_home,
            )
        )

    def _team(self, team: str, at: datetime, prefix: str, venue_home: bool) -> dict[str, float]:
        games = list(self.history.get(team, ()))
        out: dict[str, float] = {f"{prefix}_n": float(len(games))}
        for w in WINDOWS:
            last = games[-w:]
            out[f"{prefix}_ppg_{w}"] = _mean([g.points for g in last]) if last else NAN
            out[f"{prefix}_gf_{w}"] = _mean([g.gf for g in last]) if last else NAN
            out[f"{prefix}_ga_{w}"] = _mean([g.ga for g in last]) if last else NAN
        last5 = games[-5:]
        out[f"{prefix}_xgf_5"] = (
            _mean([g.xgf for g in last5 if g.xgf is not None]) if last5 else NAN
        )
        out[f"{prefix}_xga_5"] = (
            _mean([g.xga for g in last5 if g.xga is not None]) if last5 else NAN
        )
        # Rakip gücüne göre düzeltilmiş form: puan − Elo'ya göre beklenen puan (son 10).
        adj = []
        for g in games[-10:]:
            mine = self.elo.rating(team)
            exp = 1 / (
                1
                + 10
                ** (
                    -(mine - g.opp_elo + (self.elo.home_adv if g.home else -self.elo.home_adv))
                    / 400
                )
            )
            adj.append(g.points / 3 - exp)
        out[f"{prefix}_adj_form_10"] = _mean(adj) if adj else NAN
        venue = [g for g in games if g.home == venue_home][-5:]
        out[f"{prefix}_venue_gf_5"] = _mean([g.gf for g in venue]) if venue else NAN
        out[f"{prefix}_venue_ga_5"] = _mean([g.ga for g in venue]) if venue else NAN
        rest = (at - games[-1].kickoff_at).total_seconds() / 86400 if games else NAN
        out[f"{prefix}_rest_days"] = min(rest, 30.0) if not math.isnan(rest) else NAN
        return out

    def features_for(self, match: Match) -> dict[str, float]:
        f: dict[str, float] = {}
        f.update(self._team(match.home, match.kickoff_at, "h", venue_home=True))
        f.update(self._team(match.away, match.kickoff_at, "a", venue_home=False))
        f["elo_h"] = self.elo.rating(match.home)
        f["elo_a"] = self.elo.rating(match.away)
        f["elo_diff"] = f["elo_h"] - f["elo_a"]
        f["elo_exp_h"] = self.elo.expected_home(match.home, match.away)
        for key in ("ppg_5", "gf_5", "ga_5", "ppg_10", "adj_form_10", "xgf_5", "xga_5"):
            f[f"d_{key}"] = f[f"h_{key}"] - f[f"a_{key}"]
        return f


@dataclass(frozen=True)
class FeatureRow:
    match: Match
    features: dict[str, float]


def build_features(
    matches: Sequence[Match], targets: Sequence[Match] | None = None
) -> list[FeatureRow]:
    """``targets`` için (verilmezse tüm oynanmış maçlar için) özellikler.

    Tüm maçlar zaman sırasıyla işlenir; bir hedef maçın özellikleri hesaplanırken yalnızca
    ``kickoff + RESULT_DELAY <= hedef.kickoff`` olan oynanmış maçlar sisteme alınmış olur.
    """
    played = sorted((m for m in matches if m.played), key=lambda m: (m.kickoff_at, m.fixture_id))
    wanted = sorted(
        targets if targets is not None else played, key=lambda m: (m.kickoff_at, m.fixture_id)
    )
    builder = FeatureBuilder()
    rows: list[FeatureRow] = []
    i = 0
    for target in wanted:
        while i < len(played) and played[i].kickoff_at + RESULT_DELAY <= target.kickoff_at:
            builder._release(played[i])
            i += 1
        rows.append(FeatureRow(target, builder.features_for(target)))
    return rows


def matrix(
    rows: Sequence[FeatureRow], names: Sequence[str] | None = None
) -> tuple[NDArray[np.float64], list[str]]:
    cols = list(names) if names is not None else sorted(rows[0].features) if rows else []
    data = np.array([[r.features.get(c, NAN) for c in cols] for r in rows], dtype=float)
    return data.reshape(len(rows), len(cols)), cols
