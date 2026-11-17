"""Veri tazeliği ve veri tamlığı puanı.

**Tazelik:** her kaydın ``fetched_at`` zamanı, maçın durumuna göre beklenen yenileme süresiyle
karşılaştırılır. Süresi geçmiş veri ``stale=True`` olarak işaretlenir; arayüz eski veriyi canlı
gibi göstermez (ör. "Son güncelleme 14 dk önce — canlı veri gecikmeli").

**Tamlık puanı (0–100):** tahmin kalitesi değil, maç için beklenen verinin ne kadarının elimizde
olduğudur. Yalnızca sağlayıcının sunabildiği veri türleri için puan düşülür.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from mi_api.football.providers.base import Capability

LIVE_STALE = timedelta(minutes=3)
NEAR_STALE = timedelta(hours=1)  # 24 saat içinde başlayacak maç
FAR_STALE = timedelta(hours=24)


def stale_after(status: str, kickoff_at: datetime, now: datetime) -> timedelta | None:
    """Bu durumdaki maç verisi ne kadar süre sonra bayat sayılır? (None: kesinleşmiş, bayatlamaz)"""
    if status in ("live", "halftime"):
        return LIVE_STALE
    if status in ("scheduled", "tbd"):
        if kickoff_at <= now:  # başlama saati geçti ama hâlâ "başlamadı" görünüyor
            return LIVE_STALE
        return NEAR_STALE if kickoff_at - now <= timedelta(hours=24) else FAR_STALE
    if status in ("postponed", "suspended"):
        return FAR_STALE
    return None  # finished, cancelled, abandoned, awarded


def freshness(
    status: str, kickoff_at: datetime, fetched_at: datetime, now: datetime
) -> dict[str, Any]:
    age = now - fetched_at
    limit = stale_after(status, kickoff_at, now)
    return {
        "fetched_at": fetched_at.isoformat(),
        "age_s": max(0, int(age.total_seconds())),
        "stale": limit is not None and age > limit,
    }


@dataclass
class Completeness:
    score: int = 100
    issues: list[dict[str, str]] = field(default_factory=list)

    def penalize(self, points: int, code: str, message: str) -> None:
        self.score = max(0, self.score - points)
        self.issues.append({"code": code, "message": message})


def completeness(
    *,
    status: str,
    kickoff_at: datetime,
    fetched_at: datetime,
    now: datetime,
    capabilities: frozenset[Capability],
    has_stats: bool,
    has_xg: bool,
    has_lineups: bool,
    has_halftime: bool,
) -> dict[str, Any]:
    result = Completeness()
    if freshness(status, kickoff_at, fetched_at, now)["stale"]:
        result.penalize(40, "stale", "Veri güncel değil")
    if status == "finished":
        if not has_halftime:
            result.penalize(10, "no_halftime", "İlk yarı skoru yok")
        if "team_stats" in capabilities and not has_stats:
            result.penalize(20, "no_team_stats", "Maç istatistikleri henüz alınmadı")
        if "xg" in capabilities and has_stats and not has_xg:
            result.penalize(10, "no_xg", "Sağlayıcı bu maç için xG vermedi")
    if (
        status in ("scheduled", "tbd")
        and "lineups" in capabilities
        and timedelta(0) <= kickoff_at - now <= timedelta(minutes=60)
        and not has_lineups
    ):
        result.penalize(15, "no_lineups", "İlk 11'ler henüz açıklanmadı")
    return {"score": result.score, "issues": result.issues}
