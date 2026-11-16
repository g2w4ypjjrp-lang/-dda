"""Hız sınırı: kayan pencere. Redis varsa tüm örnekler arasında paylaşılır.

Redis uygulaması sıralı küme (ZSET) + tek Lua betiği ile atomiktir. Redis'e ulaşılamazsa
istek **reddedilmez** (kimlik doğrulamayı kilitlememek için) ama süreç içi sınıra düşülür ve
log yazılır; üretimde Redis zorunludur (ayar doğrulaması).
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)


class Limiter(Protocol):
    async def allow(self, key: str, limit: int, window_s: float) -> bool: ...

    async def reset(self, key: str) -> None: ...


class MemoryLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = self.clock()
        bucket = self.hits[key]
        while bucket and now - bucket[0] > window_s:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    async def reset(self, key: str) -> None:
        self.hits.pop(key, None)


_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return 1
"""


class RedisLimiter:
    def __init__(self, redis: Redis, *, prefix: str = "mi:rl:") -> None:
        self.redis = redis
        self.prefix = prefix
        self.fallback = MemoryLimiter()
        self._script = redis.register_script(_LUA)

    async def allow(self, key: str, limit: int, window_s: float) -> bool:
        try:
            result = await self._script(
                keys=[self.prefix + key],
                args=[time.time(), window_s, limit, secrets.token_hex(8)],
            )
            return bool(result)
        except (RedisError, OSError) as exc:
            log.warning("Redis hız sınırı kullanılamadı, süreç içi sınıra düşüldü: %s", exc)
            return await self.fallback.allow(key, limit, window_s)

    async def reset(self, key: str) -> None:
        with contextlib.suppress(RedisError, OSError):
            await self.redis.delete(self.prefix + key)
        await self.fallback.reset(key)
