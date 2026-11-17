"""Sağlayıcı kota bütçesi.

İki katman: (1) yerel sayaçlar (dakika ve UTC günü; Redis varsa tüm işçiler arasında paylaşılır),
(2) sağlayıcının yanıt başlıklarında bildirdiği kalan hak. Hangisi daha kısıtlayıcıysa o geçerlidir.

Öncelik: ``high`` (canlı maç, günün fikstürü) bütçenin tamamını kullanabilir; ``low`` (kadro,
istatistik, puan durumu, geçmiş veri) günlük bütçenin ``reserve_pct``'lik son dilimine giremez.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from mi_api.football.providers.base import QuotaExceeded, QuotaInfo

log = logging.getLogger(__name__)
Priority = Literal["high", "low"]


class QuotaBudget:
    def __init__(
        self,
        provider: str,
        *,
        daily: int,
        minute: int,
        reserve_pct: int,
        clock: Callable[[], datetime],
        redis: Redis | None = None,
    ) -> None:
        self.provider = provider
        self.daily = daily
        self.minute = minute
        self.reserve_pct = reserve_pct
        self.clock = clock
        self.redis = redis
        self.memory: dict[str, int] = defaultdict(int)
        self.observed: QuotaInfo | None = None
        self.priority: Priority = "high"

    def _keys(self) -> tuple[str, str]:
        now = self.clock()
        base = f"mi:quota:{self.provider}"
        return f"{base}:d:{now:%Y%m%d}", f"{base}:m:{int(now.timestamp() // 60)}"

    def daily_cap(self, priority: Priority) -> int:
        if priority == "high":
            return self.daily
        return max(0, self.daily - (self.daily * self.reserve_pct) // 100)

    async def _incr(self, key: str, ttl_s: int, delta: int = 1) -> int:
        if self.redis is not None:
            try:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.incrby(key, delta)
                    pipe.expire(key, ttl_s)
                    value, _ = await pipe.execute()
                return int(value)
            except (RedisError, OSError) as exc:
                log.warning("Kota sayacı Redis'e yazılamadı, süreç içi sayaca düşüldü: %s", exc)
        self.memory[key] += delta
        return self.memory[key]

    async def acquire(self) -> None:
        """Bir istek hakkı ayırır; yoksa ``QuotaExceeded``."""
        priority = self.priority
        observed = self.observed
        reserve = (self.daily * self.reserve_pct) // 100 if priority == "low" else 0
        if (
            observed
            and observed.daily_remaining is not None
            and observed.daily_remaining <= reserve
        ):
            remaining = observed.daily_remaining
            raise QuotaExceeded(
                f"{self.provider}: sağlayıcının bildirdiği günlük kalan hak {remaining}"
            )
        if observed and observed.minute_remaining is not None and observed.minute_remaining <= 0:
            raise QuotaExceeded(f"{self.provider}: sağlayıcının dakikalık hakkı doldu")
        day_key, minute_key = self._keys()
        used_day = await self._incr(day_key, 2 * 86400)
        if used_day > self.daily_cap(priority):
            await self._incr(day_key, 2 * 86400, -1)
            cap = self.daily_cap(priority)
            raise QuotaExceeded(f"{self.provider}: günlük yerel bütçe doldu ({priority}, {cap})")
        used_minute = await self._incr(minute_key, 120)
        if used_minute > self.minute:
            await self._incr(minute_key, 120, -1)
            await self._incr(day_key, 2 * 86400, -1)
            raise QuotaExceeded(f"{self.provider}: dakikalık yerel bütçe doldu ({self.minute})")

    async def observe(self, info: QuotaInfo) -> None:
        self.observed = info

    async def used_today(self) -> int:
        day_key, _ = self._keys()
        if self.redis is not None:
            try:
                value = await self.redis.get(day_key)
                return int(value or 0)
            except (RedisError, OSError):
                pass
        return self.memory.get(day_key, 0)
