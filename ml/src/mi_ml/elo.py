"""Elo derecelendirmesi (ev sahibi avantajı ve gol farkı çarpanıyla).

Maçlar kronolojik işlenir; her maç için **maç öncesi** dereceler döner (özellik olarak sızıntısız
kullanılabilir). Gol farkı çarpanı Dünya Futbol Elo yöntemindedir: fark ≤1 → 1, 2 → 1.5,
≥3 → (11 + fark) / 8. Yeni takım ``initial`` ile başlar.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from mi_ml.dixon_coles import MatchRecord


def goal_multiplier(diff: int) -> float:
    diff = abs(diff)
    if diff <= 1:
        return 1.0
    if diff == 2:
        return 1.5
    return (11 + diff) / 8


@dataclass
class Elo:
    k: float = 20.0
    home_adv: float = 60.0
    initial: float = 1500.0
    ratings: dict[str, float] = field(default_factory=dict)
    games: dict[str, int] = field(default_factory=dict)

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.initial)

    def expected_home(self, home: str, away: str) -> float:
        diff = self.rating(home) + self.home_adv - self.rating(away)
        return 1.0 / (1.0 + 10 ** (-diff / 400))

    def update(self, match: MatchRecord) -> tuple[float, float]:
        """Maçı işler; maç öncesi (ev, deplasman) derecelerini döner."""
        before = (self.rating(match.home), self.rating(match.away))
        expected = self.expected_home(match.home, match.away)
        if match.home_goals > match.away_goals:
            actual = 1.0
        elif match.home_goals == match.away_goals:
            actual = 0.5
        else:
            actual = 0.0
        delta = self.k * goal_multiplier(match.home_goals - match.away_goals) * (actual - expected)
        self.ratings[match.home] = before[0] + delta
        self.ratings[match.away] = before[1] - delta
        for team in (match.home, match.away):
            self.games[team] = self.games.get(team, 0) + 1
        return before

    def run(self, matches: Iterable[MatchRecord]) -> list[tuple[float, float]]:
        ordered = sorted(matches, key=lambda m: m.kickoff_at)
        return [self.update(m) for m in ordered]
