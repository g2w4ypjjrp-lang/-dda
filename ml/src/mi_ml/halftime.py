"""İlk yarı (İY) modeli: tam maç skor dağılımının yarılara ayrıştırılması.

**Yöntem (binom inceltme).** Bir takımın 90 dakikada attığı her gol, birbirinden bağımsız olarak
``r`` olasılıkla ilk yarıda atılmış kabul edilir. Böylece tam maç skor matrisi ``M[i, j]``'den

    P(İY = (a, b), MS = (i, j)) = M[i, j] · Binom(a; i, r_ev) · Binom(b; j, r_dep)

ortak dağılımı elde edilir. Sonuçları:

* İY piyasaları (1X2, alt/üst, karşılıklı gol, doğru skor) ve **İY/MS** aynı ortak dağılımdan
  türetilir; tam maç olasılıkları değişmez (marjinal = ``M``). Kupon motoru aynı maçta İY ve MS
  seçimlerinin birleşik olasılığını bu dağılımdan **kesin** hesaplar.
* ``r`` eğitim verisinde gözlenen İY gol payıdır (ev/deplasman ayrı, Beta(2, 2) önsel ile
  düzleştirilmiş en çok olabilirlik). İY skoru eksik maçlar ``r`` tahmininde kullanılmaz.

**Değerlendirme.** Test döneminde (ana modelle aynı dönem) 30 günlük pencerelerle, her pencere
öncesi yalnızca o ana kadar kesinleşmiş verilerle Dixon-Coles ve ``r`` yeniden eğitilir; İY 1X2
için log loss, Brier ve ECE ölçülür ve **saf temel çizgiyle** (eğitim dönemindeki İY sonuç
frekansları) karşılaştırılır. İY piyasaları yalnızca: yeterli test örneklemi, yeterli İY skoru
kapsamı, temel çizgiden iyi log loss ve kabul edilebilir kalibrasyon varsa yayımlanır; aksi halde
tahmin kaydında nedeniyle birlikte "kullanılamaz" yazılır.

Varsayım: golün yarıya düşme olasılığı skor durumundan bağımsızdır. Gerçekte oyun durumu (önde
olan takımın temkinli oynaması) bu bağımsızlığı bozabilir; bu yüzden ölçülmeden yayımlanmaz.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import binom

from mi_ml.dixon_coles import DixonColes, UnknownTeam
from mi_ml.features import RESULT_DELAY, Match
from mi_ml.metrics import CLASSES, brier, ece, log_loss, outcome_label

FloatArray = NDArray[np.float64]
HT_LINES = (0.5, 1.5, 2.5)
HTFT = tuple(f"{a}/{b}" for a in ("1", "X", "2") for b in ("1", "X", "2"))
PRIOR = 2.0  # Beta(2, 2)


@dataclass(frozen=True)
class Split:
    home: float
    away: float
    n_matches: int
    n_goals: int


def fit_split(matches: Sequence[Match]) -> Split | None:
    """İY gol payı ``r`` (ev, deplasman). İY skoru olan maç yoksa ``None``."""
    rows = [m for m in matches if m.ht_home is not None and m.ht_away is not None]
    if not rows:
        return None
    hh = sum(m.ht_home or 0 for m in rows)
    ha = sum(m.ht_away or 0 for m in rows)
    fh = sum(m.home_goals for m in rows)
    fa = sum(m.away_goals for m in rows)
    return Split(
        home=(hh + PRIOR - 1) / (fh + 2 * PRIOR - 2),
        away=(ha + PRIOR - 1) / (fa + 2 * PRIOR - 2),
        n_matches=len(rows),
        n_goals=fh + fa,
    )


def thinning(n: int, r: float) -> FloatArray:
    """``B[i, a] = Binom(a; i, r)`` (i, a = 0..n-1)."""
    goals = np.arange(n)
    return np.asarray(binom.pmf(goals[None, :], goals[:, None], r), dtype=np.float64)


def joint(ft: FloatArray, split: tuple[float, float]) -> FloatArray:
    """4B ortak dağılım ``T[i, j, a, b] = P(MS=(i,j), İY=(a,b))``."""
    n = ft.shape[0]
    bh, ba = thinning(n, split[0]), thinning(n, split[1])
    return np.asarray(np.einsum("ij,ia,jb->ijab", ft, bh, ba), dtype=np.float64)


def ht_matrix(ft: FloatArray, split: tuple[float, float]) -> FloatArray:
    n = ft.shape[0]
    bh, ba = thinning(n, split[0]), thinning(n, split[1])
    return np.asarray(bh.T @ ft @ ba, dtype=np.float64)


def _result_masks(n: int) -> dict[str, NDArray[np.bool_]]:
    g = np.arange(n)
    diff = g[:, None] - g[None, :]
    return {"1": diff > 0, "X": diff == 0, "2": diff < 0}


def one_x_two(m: FloatArray) -> dict[str, float]:
    masks = _result_masks(m.shape[0])
    home, draw = float(m[masks["1"]].sum()), float(m[masks["X"]].sum())
    return {"home": home, "draw": draw, "away": 1.0 - home - draw}


def ht_ft(ft: FloatArray, split: tuple[float, float]) -> dict[str, float]:
    t = joint(ft, split)
    masks = _result_masks(ft.shape[0])
    out = {}
    for a in ("1", "X", "2"):
        ht_part = t[:, :, masks[a]].sum(axis=2)  # (i, j)
        for b in ("1", "X", "2"):
            out[f"{a}/{b}"] = float(ht_part[masks[b]].sum())
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


def markets(ft: FloatArray, split: tuple[float, float]) -> dict[str, Any]:
    """Tahmin kaydına yazılan İY piyasaları (``ft`` normalize skor matrisi)."""
    ft = ft / ft.sum()
    ht = ht_matrix(ft, split)
    n = ht.shape[0]
    totals = np.add.outer(np.arange(n), np.arange(n))
    ou = {}
    for line in HT_LINES:
        over = float(ht[totals > line].sum())
        ou[f"{line:.1f}"] = {"over": over, "under": 1.0 - over}
    flat = np.argsort(ht, axis=None)[::-1][:6]
    rows, cols = np.unravel_index(flat, ht.shape)
    goals = np.arange(n)
    return {
        "available": True,
        "split": {"home": split[0], "away": split[1]},
        "1x2": one_x_two(ht),
        "over_under": ou,
        "btts": {"yes": float(ht[1:, 1:].sum()), "no": float(1.0 - ht[1:, 1:].sum())},
        "correct_score": [
            {"home": int(r), "away": int(c), "p": float(ht[r, c])}
            for r, c in zip(rows, cols, strict=True)
        ],
        "expected_goals": {
            "home": float((ht.sum(axis=1) * goals).sum()),
            "away": float((ht.sum(axis=0) * goals).sum()),
        },
        "ht_ft": ht_ft(ft, split),
    }


# --- Değerlendirme -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    min_test_n: int = 100
    min_coverage: float = 0.8
    max_ece: float = 0.08


def _baseline(matches: Sequence[Match]) -> FloatArray:
    counts = np.ones(3)  # Laplace
    for m in matches:
        counts[outcome_label(m.ht_home or 0, m.ht_away or 0)] += 1
    return counts / counts.sum()


def _windows(first: Any, last: Any, days: int) -> list[tuple[Any, Any]]:
    out, t = [], first
    while t <= last:
        out.append((t, t + timedelta(days=days)))
        t += timedelta(days=days)
    return out


def evaluate(
    played: Sequence[Match],
    test_from: Any,
    *,
    xi: float = 0.0019,
    window_days: int = 30,
    gate: Gate | None = None,
) -> dict[str, Any]:
    """Test döneminde örneklem dışı İY değerlendirmesi ve yayın kararı (JSON'a uygun)."""
    gate = gate or Gate()
    train = [m for m in played if m.kickoff_at < test_from]
    coverage = (
        sum(1 for m in train if m.ht_home is not None and m.ht_away is not None) / len(train)
        if train
        else 0.0
    )
    tests = [m for m in played if m.kickoff_at >= test_from and m.ht_home is not None]
    probs, base, labels, htft_ll, htft_base = [], [], [], [], []
    for lo, hi in _windows(test_from, tests[-1].kickoff_at, window_days) if tests else []:
        idx = [m for m in tests if lo <= m.kickoff_at < hi]
        if not idx:
            continue
        cutoff = lo - RESULT_DELAY
        known = [m for m in played if m.kickoff_at <= cutoff]
        split = fit_split(known)
        if split is None or len(known) < 30:
            continue
        model = DixonColes(xi=xi, fit_rho=True).fit(known, as_of=max(m.kickoff_at for m in known))
        b = _baseline(known)
        htft_freq = np.ones(9)
        for m in known:
            if m.ht_home is not None and m.ht_away is not None:
                key = f"{'1X2'[outcome_label(m.ht_home, m.ht_away)]}/{'1X2'[outcome_label(m.home_goals, m.away_goals)]}"
                htft_freq[HTFT.index(key)] += 1
        htft_freq /= htft_freq.sum()
        for m in idx:
            try:
                ft = model.score_matrix(m.home, m.away).probs
            except UnknownTeam:
                continue
            ht = ht_matrix(ft, (split.home, split.away))
            x = one_x_two(ht)
            probs.append([x[k] for k in CLASSES])
            base.append(b)
            label = outcome_label(m.ht_home or 0, m.ht_away or 0)
            labels.append(label)
            key = f"{'1X2'[label]}/{'1X2'[outcome_label(m.home_goals, m.away_goals)]}"
            p9 = ht_ft(ft, (split.home, split.away))
            htft_ll.append(-np.log(max(p9[key], 1e-15)))
            htft_base.append(-np.log(htft_freq[HTFT.index(key)]))
    full = fit_split(played)
    result: dict[str, Any] = {
        "method": "binomial_thinning",
        "split": {"home": full.home, "away": full.away} if full else None,
        "coverage": coverage,
        "test": {"n": len(labels)},
    }
    reasons = []
    if full is None:
        reasons.append("İlk yarı skoru verisi yok")
    if coverage < gate.min_coverage:
        reasons.append(f"Eğitim verisinde İY skoru kapsamı düşük (%{coverage * 100:.0f})")
    if len(labels) < gate.min_test_n:
        reasons.append(f"İY test örneklemi yetersiz ({len(labels)} < {gate.min_test_n})")
    if labels:
        p, y, bp = np.array(probs), np.array(labels), np.array(base)
        p = p / p.sum(axis=1, keepdims=True)
        result["test"].update(
            {
                "log_loss": log_loss(p, y),
                "brier": brier(p, y),
                "ece": ece(p, y),
                "baseline_log_loss": log_loss(bp, y),
                "ht_ft_log_loss": float(np.mean(htft_ll)),
                "ht_ft_baseline_log_loss": float(np.mean(htft_base)),
            }
        )
        t = result["test"]
        if t["log_loss"] >= t["baseline_log_loss"]:
            reasons.append("İY modeli testte saf temel çizgiden iyi değil")
        if t["ece"] > gate.max_ece:
            reasons.append(f"İY kalibrasyonu zayıf (ECE {t['ece']:.3f})")
        if t["ht_ft_log_loss"] >= t["ht_ft_baseline_log_loss"]:
            reasons.append("İY/MS testte saf temel çizgiden iyi değil")
    result["available"] = not reasons
    result["reasons"] = reasons
    return result
