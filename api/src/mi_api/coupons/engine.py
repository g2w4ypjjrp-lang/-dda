"""Kupon motoru: seçim tanımları, birleşik olasılık, Monte Carlo doğrulaması, otomatik kupon.

**Birleşik olasılık nasıl hesaplanır?**

* Aynı maçtaki seçimler bağımsız **değildir** (ör. "1" ve "2.5 Üst"). Bu yüzden çarpılmaz; tahmin
  kaydındaki ortak skor dağılımından (``score_matrix``, 0–10 gol) tüm seçimlerin **birlikte**
  gerçekleştiği skorların olasılıkları toplanır. Bu kesin değerdir.
* İlk yarı (İY) seçimleri için aynı dağılım, tahmin kaydındaki İY gol payıyla (``first_half.split``)
  binom inceltmeyle İY × MS ortak dağılımına genişletilir; "İY 1 + MS 2.5 Üst" gibi seçimler de
  kesin hesaplanır. İY modeli testte geçmediyse İY seçimi yapılamaz.
* Farklı maçlar, model koşulunda birbirinden bağımsızdır (her maçın skor dağılımı ayrı tahmin
  edilir). Maç başına birleşik olasılıklar çarpılır. Bu varsayım raporda açıkça yazılır.
* Monte Carlo (sabit tohum, 10.000 ve 50.000 simülasyon) her maçın skorunu kendi dağılımından
  örnekler ve kuponu bütün olarak değerlendirir. Kesin değerle uyuşması (standart hata içinde)
  hesaplamanın doğrulamasıdır. Simülasyon sayısını artırmak modelin doğruluğunu artırmaz.

**Oran yok (M-G2):** lisanslı oran verisi bağlanana kadar toplam oran ve beklenen değer (EV)
hesaplanmaz; kupon yalnızca model olasılığıyla sunulur. Hiçbir profil kazanç garantisi değildir.

Bu modül saf Python'dur (API imajına bilimsel kütüphane eklenmez).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

# Seçim koşulu: (MS ev, MS deplasman, İY ev, İY deplasman) golleri.
Predicate = Callable[[int, int, int, int], bool]
Profile = Literal["low", "balanced", "high"]
SEED = 42
MC_SIZES = (10_000, 50_000)


@dataclass(frozen=True)
class Market:
    code: str
    pick: str
    label: str
    predicate: Predicate
    half: bool = False  # İY skoruna bağlı mı?


def _ou(line: float, over: bool) -> Predicate:
    return (lambda h, a, *_: h + a > line) if over else (lambda h, a, *_: h + a < line)


def _res(x: int, y: int) -> str:
    return "1" if x > y else "X" if x == y else "2"


_DEFS: list[Market] = [
    Market("1x2", "home", "Maç sonucu: 1", lambda h, a, *_: h > a),
    Market("1x2", "draw", "Maç sonucu: X", lambda h, a, *_: h == a),
    Market("1x2", "away", "Maç sonucu: 2", lambda h, a, *_: h < a),
    Market("double_chance", "1X", "Çifte şans: 1X", lambda h, a, *_: h >= a),
    Market("double_chance", "12", "Çifte şans: 12", lambda h, a, *_: h != a),
    Market("double_chance", "X2", "Çifte şans: X2", lambda h, a, *_: h <= a),
    Market("btts", "yes", "Karşılıklı gol: Var", lambda h, a, *_: h > 0 and a > 0),
    Market("btts", "no", "Karşılıklı gol: Yok", lambda h, a, *_: h == 0 or a == 0),
]
for _line in (1.5, 2.5, 3.5):
    _DEFS.append(Market("total", f"over_{_line}", f"{_line} Üst", _ou(_line, True)))
    _DEFS.append(Market("total", f"under_{_line}", f"{_line} Alt", _ou(_line, False)))
# İlk yarı (İY) piyasaları: yalnızca İY modeli testte geçtiyse tahmin kaydında bulunur.
_DEFS += [
    Market("ht_1x2", "home", "İlk yarı: 1", lambda h, a, x, y: x > y, half=True),
    Market("ht_1x2", "draw", "İlk yarı: X", lambda h, a, x, y: x == y, half=True),
    Market("ht_1x2", "away", "İlk yarı: 2", lambda h, a, x, y: x < y, half=True),
]


def _ht_ou(line: float, over: bool) -> Predicate:
    return (lambda h, a, x, y: x + y > line) if over else (lambda h, a, x, y: x + y < line)


def _htft(ht: str, ft: str) -> Predicate:
    return lambda h, a, x, y: _res(x, y) == ht and _res(h, a) == ft


for _line in (0.5, 1.5):
    _DEFS.append(Market("ht_total", f"over_{_line}", f"İY {_line} Üst", _ht_ou(_line, True), True))
    _DEFS.append(
        Market("ht_total", f"under_{_line}", f"İY {_line} Alt", _ht_ou(_line, False), True)
    )
for _a in ("1", "X", "2"):
    for _b in ("1", "X", "2"):
        _DEFS.append(Market("ht_ft", f"{_a}/{_b}", f"İY/MS: {_a}/{_b}", _htft(_a, _b), True))
MARKETS: dict[tuple[str, str], Market] = {(m.code, m.pick): m for m in _DEFS}
MARKET_CODES = frozenset(m.code for m in _DEFS)


class CouponError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def market(code: str, pick: str) -> Market:
    m = MARKETS.get((code, pick))
    if m is None:
        raise CouponError("unknown_market", f"Bilinmeyen piyasa: {code} / {pick}")
    return m


_HT_KEY = {"home": "home", "draw": "draw", "away": "away"}


def first_half(probabilities: dict[str, Any]) -> dict[str, Any] | None:
    fh = probabilities.get("first_half")
    return fh if isinstance(fh, dict) and fh.get("available") and fh.get("split") else None


def stored_probability(probabilities: dict[str, Any], code: str, pick: str) -> float | None:
    """Tek seçim olasılığı tahmin kaydındaki yayımlanmış piyasalardan okunur."""
    if code.startswith("ht_"):
        fh = first_half(probabilities)
        if fh is None:
            return None
        if code == "ht_1x2":
            return float(fh["1x2"][pick])
        if code == "ht_ft":
            return float(fh["ht_ft"][pick])
        side, line = pick.split("_")
        entry = fh.get("over_under", {}).get(line)
        return float(entry[side]) if entry else None
    if code == "1x2":
        return float(probabilities["1x2"][pick])
    if code == "double_chance":
        return float(probabilities["double_chance"][pick])
    if code == "btts":
        return float(probabilities["btts"][pick])
    if code == "total":
        side, line = pick.split("_")
        entry = probabilities.get("over_under", {}).get(line)
        return float(entry[side]) if entry else None
    return None


@dataclass(frozen=True)
class Leg:
    """Kupon seçimi. ``matrix`` tahmin kaydındaki ortak skor dağılımıdır (yoksa None)."""

    fixture_id: int
    market: Market
    probabilities: dict[str, Any]

    @property
    def matrix(self) -> list[list[float]] | None:
        m = self.probabilities.get("score_matrix")
        return m if isinstance(m, list) and m else None

    @property
    def split(self) -> tuple[float, float] | None:
        fh = first_half(self.probabilities)
        return (float(fh["split"]["home"]), float(fh["split"]["away"])) if fh else None


def _binom(n: int, r: float) -> list[float]:
    return [math.comb(n, k) * r**k * (1 - r) ** (n - k) for k in range(n + 1)]


def _cells(
    matrix: list[list[float]], split: tuple[float, float] | None
) -> list[tuple[int, int, int, int, float]]:
    """Ortak dağılımın hücreleri. İY gerekiyorsa her MS skoru binom inceltmeyle İY skorlarına
    ayrılır (ML ``halftime`` modülüyle aynı model):
    P = M[h][a] · Binom(x; h, r_ev) · Binom(y; a, r_dep)."""
    total = sum(map(sum, matrix))
    out = []
    for h, row in enumerate(matrix):
        for a, p in enumerate(row):
            if p <= 0:
                continue
            if split is None:
                out.append((h, a, -1, -1, p / total))
                continue
            bh, ba = _binom(h, split[0]), _binom(a, split[1])
            for x, px in enumerate(bh):
                for y, py in enumerate(ba):
                    out.append((h, a, x, y, p * px * py / total))
    return out


def _group_split(legs: Sequence[Leg]) -> tuple[float, float] | None:
    if not any(leg.market.half for leg in legs):
        return None
    split = legs[0].split
    if split is None:
        raise CouponError("market_unavailable", "Bu maç için ilk yarı tahmini yayımlanmadı")
    return split


def fixture_joint(legs: Sequence[Leg]) -> float:
    """Aynı maçtaki seçimlerin birlikte gerçekleşme olasılığı (kesin)."""
    if len(legs) == 1 and legs[0].market.half:
        # Tek İY seçimi: tahmin kaydında yayımlanan değer (aynı dağılımdan hesaplanmıştır).
        p = stored_probability(legs[0].probabilities, legs[0].market.code, legs[0].market.pick)
        if p is None:
            raise CouponError("market_unavailable", "Bu maç için ilk yarı tahmini yayımlanmadı")
        return p
    matrix = legs[0].matrix
    if matrix is None:
        if len(legs) > 1:
            raise CouponError(
                "joint_unavailable",
                "Bu maçın tahmin kaydında ortak skor dağılımı "
                "yok; aynı maçtan birden fazla seçim yapılamaz",
            )
        p = stored_probability(legs[0].probabilities, legs[0].market.code, legs[0].market.pick)
        if p is None:
            raise CouponError("market_unavailable", "Bu piyasa için olasılık yok")
        return p
    split = _group_split(legs)
    preds = [leg.market.predicate for leg in legs]
    return sum(
        c[4] for c in _cells(matrix, split) if all(pr(c[0], c[1], c[2], c[3]) for pr in preds)
    )


def group(legs: Sequence[Leg]) -> dict[int, list[Leg]]:
    out: dict[int, list[Leg]] = {}
    for leg in legs:
        out.setdefault(leg.fixture_id, []).append(leg)
    return out


def joint_probability(legs: Sequence[Leg]) -> float:
    if not legs:
        raise CouponError("empty", "Kupon en az bir seçim içermeli")
    return math.prod(fixture_joint(g) for g in group(legs).values())


@dataclass(frozen=True)
class SimResult:
    n: int
    seed: int
    p: float
    std_error: float


def simulate(legs: Sequence[Leg], n: int, seed: int = SEED) -> SimResult:
    """Her maçın MS skoru kendi dağılımından örneklenir; İY seçimi varsa her gol ayrıca ``r``
    olasılıkla ilk yarıya atanır (kesin hesaptan bağımsız bir yol)."""
    rng = random.Random(seed)  # noqa: S311 - simülasyon, kriptografi değil (tekrar üretilebilir tohum)
    groups = list(group(legs).values())
    hits = [True] * n
    for g in groups:
        matrix = g[0].matrix
        if matrix is None:
            p = fixture_joint(g)
            outcome = [rng.random() < p for _ in range(n)]
        else:
            split = _group_split(g)
            size = len(matrix[0])
            cells = [(h, a) for h in range(len(matrix)) for a in range(size)]
            weights = [matrix[h][a] for h, a in cells]
            draws = rng.choices(range(len(cells)), weights=weights, k=n)
            preds = [leg.market.predicate for leg in g]
            outcome = []
            for d in draws:
                h, a = cells[d]
                if split is None:
                    x = y = -1
                else:
                    x = sum(rng.random() < split[0] for _ in range(h))
                    y = sum(rng.random() < split[1] for _ in range(a))
                outcome.append(all(pr(h, a, x, y) for pr in preds))
        hits = [x and y for x, y in zip(hits, outcome, strict=True)]
    p = sum(hits) / n
    return SimResult(n, seed, p, math.sqrt(max(p * (1 - p), 1e-12) / n))


@dataclass
class Evaluation:
    joint_probability: float
    simulations: list[SimResult]
    converged: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "joint_probability": self.joint_probability,
            "one_in": round(1 / self.joint_probability, 1) if self.joint_probability > 0 else None,
            "monte_carlo": {
                "runs": [
                    {"n": s.n, "seed": s.seed, "p": s.p, "std_error": s.std_error}
                    for s in self.simulations
                ],
                "converged": self.converged,
                "note": (
                    "Simülasyon kesin hesabı doğrular; "
                    "sayısını artırmak model doğruluğunu artırmaz."
                ),
            },
            "assumption": (
                "Aynı maçtaki seçimler ortak skor "
                "dağılımından; farklı maçlar model koşulunda bağımsız."
            ),
        }


def evaluate(legs: Sequence[Leg], sizes: Sequence[int] = MC_SIZES, seed: int = SEED) -> Evaluation:
    exact = joint_probability(legs)
    sims = [simulate(legs, n, seed + i) for i, n in enumerate(sizes)]
    converged = all(abs(s.p - exact) <= 4 * s.std_error + 1e-9 for s in sims)
    return Evaluation(exact, sims, converged)


# --- Otomatik kupon ------------------------------------------------------------------------------

# Profil: seçim olasılığı bandı ve kabul edilen model güvenilirliği. Düşük risk = yüksek olasılıklı
# seçimler; yüksek risk = daha düşük olasılıklı seçimler. Hiçbiri garanti değildir.
PROFILES: dict[str, dict[str, Any]] = {
    "low": {"min_p": 0.70, "max_p": 1.0, "reliability": {"high", "medium"}},
    "balanced": {"min_p": 0.55, "max_p": 0.78, "reliability": {"high", "medium"}},
    "high": {"min_p": 0.38, "max_p": 0.62, "reliability": {"high", "medium", "low"}},
}
RELIABILITY_WEIGHT = {"high": 1.0, "medium": 0.95, "low": 0.85}


@dataclass(frozen=True)
class Candidate:
    """Yayımlanmış bir tahmin ve onun bilgileri (API katmanı doldurur)."""

    prediction_id: int
    fixture_id: int
    probabilities: dict[str, Any]
    reliability: str
    info: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Pick:
    candidate: Candidate
    market: Market
    probability: float


def best_pick(c: Candidate, profile: Profile, markets: frozenset[str] | None) -> Pick | None:
    rules = PROFILES[profile]
    if c.reliability not in rules["reliability"]:
        return None
    best: Pick | None = None
    for m in _DEFS:
        if markets and m.code not in markets:
            continue
        leg = Leg(c.fixture_id, m, c.probabilities)
        try:
            p = fixture_joint([leg])
        except CouponError:
            continue
        if rules["min_p"] <= p <= rules["max_p"] and (best is None or p > best.probability):
            best = Pick(c, m, p)
    return best


def build(
    candidates: Sequence[Candidate],
    *,
    profile: Profile,
    size: int,
    markets: frozenset[str] | None = None,
) -> list[Pick]:
    """Maç başına en fazla bir seçim; en olası (güvenilirlikle ağırlıklı) ``size`` maç."""
    picks = [p for c in candidates if (p := best_pick(c, profile, markets)) is not None]
    picks.sort(
        key=lambda p: (
            p.probability * RELIABILITY_WEIGHT.get(p.candidate.reliability, 0.8),
            -p.candidate.fixture_id,
        ),
        reverse=True,
    )
    if len(picks) < size:
        raise CouponError(
            "insufficient_candidates",
            f"Bu profil ve filtrelerle yalnızca {len(picks)} uygun maç var ({size} istendi)",
        )
    return picks[:size]


def risk_text(p: float, legs: int, min_reliability: str) -> str:
    one_in = 1 / p if p > 0 else float("inf")
    rel = {"high": "yüksek", "medium": "orta", "low": "düşük"}.get(min_reliability, min_reliability)
    return (
        f"Modele göre bu {legs} seçimin hepsinin gerçekleşme olasılığı %{p * 100:.1f}; "
        f"yaklaşık her {one_in:.1f} benzer kupondan 1'i tutar. "
        f"En zayıf seçimin model güvenilirliği {rel}. Olasılıklar kesin sonuç değildir; "
        "seçim sayısı arttıkça birleşik olasılık hızla düşer."
    )
