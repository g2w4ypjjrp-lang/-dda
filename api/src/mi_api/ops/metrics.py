# ruff: noqa: E501
"""İstek metrikleri ve hata halkası (System Health, Action Center, Log Merkezi).

Her isteğin süresi ve durumu dakikalık kovalarda toplanır (Redis varsa paylaşımlı, yoksa süreç
içi). 5xx yanıtları son 200 kayıtlık halkada tutulur: zaman, yöntem, yol, durum, istek kimliği.
İstek gövdesi, sorgu parametresi veya kullanıcı bilgisi **yazılmaz**.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Protocol

from redis.asyncio import Redis

BUCKET_TTL_S = 3 * 3600
ERROR_RING = 200
SKIP = ("/health", "/ready")


def _minute(ts: float) -> int:
    return int(ts // 60)


class Metrics(Protocol):
    async def record(self, method: str, path: str, status: int, ms: float, rid: str) -> None: ...
    async def window(self, minutes: int) -> dict[str, Any]: ...
    async def errors(self, limit: int) -> list[dict[str, Any]]: ...


def _summary(rows: list[tuple[int, int, float, float]], minutes: int) -> dict[str, Any]:
    req = sum(r[0] for r in rows)
    err = sum(r[1] for r in rows)
    lat = sum(r[2] for r in rows)
    mx = max((r[3] for r in rows), default=0.0)
    return {
        "minutes": minutes,
        "requests": req,
        "errors_5xx": err,
        "error_rate": round(err / req, 4) if req else None,
        "avg_ms": round(lat / req, 1) if req else None,
        "max_ms": round(mx, 1) if req else None,
    }


class MemoryMetrics:
    def __init__(self) -> None:
        self.buckets: dict[int, list[float]] = {}
        self.ring: deque[dict[str, Any]] = deque(maxlen=ERROR_RING)

    async def record(self, method: str, path: str, status: int, ms: float, rid: str) -> None:
        if path in SKIP:
            return
        now = time.time()
        b = self.buckets.setdefault(_minute(now), [0, 0, 0.0, 0.0])
        b[0] += 1
        b[1] += 1 if status >= 500 else 0
        b[2] += ms
        b[3] = max(b[3], ms)
        for k in [k for k in self.buckets if k < _minute(now) - BUCKET_TTL_S // 60]:
            del self.buckets[k]
        if status >= 500:
            self.ring.appendleft(
                {"ts": now, "method": method, "path": path, "status": status, "request_id": rid}
            )

    async def window(self, minutes: int) -> dict[str, Any]:
        start = _minute(time.time()) - minutes + 1
        rows = [(int(v[0]), int(v[1]), v[2], v[3]) for k, v in self.buckets.items() if k >= start]
        return _summary(rows, minutes)

    async def errors(self, limit: int) -> list[dict[str, Any]]:
        return list(self.ring)[:limit]


class RedisMetrics:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def record(self, method: str, path: str, status: int, ms: float, rid: str) -> None:
        if path in SKIP:
            return
        now = time.time()
        key = f"mi:metrics:{_minute(now)}"
        try:
            pipe = self.redis.pipeline()
            pipe.hincrby(key, "req", 1)
            if status >= 500:
                pipe.hincrby(key, "err", 1)
            pipe.hincrbyfloat(key, "lat", ms)
            pipe.expire(key, BUCKET_TTL_S)
            if status >= 500:
                entry = {
                    "ts": now,
                    "method": method,
                    "path": path,
                    "status": status,
                    "request_id": rid,
                }
                pipe.lpush("mi:errors", json.dumps(entry))
                pipe.ltrim("mi:errors", 0, ERROR_RING - 1)
            await pipe.execute()
            # En uzun süre: dakikalık anahtarda karşılaştırmalı güncelleme (yaklaşık; yarış zararsız).
            cur = await self.redis.hget(key, "max")
            if cur is None or float(cur) < ms:
                await self.redis.hset(key, "max", ms)
        except Exception:
            return

    async def window(self, minutes: int) -> dict[str, Any]:
        now = _minute(time.time())
        pipe = self.redis.pipeline()
        for m in range(now - minutes + 1, now + 1):
            pipe.hgetall(f"mi:metrics:{m}")
        rows = []
        for h in await pipe.execute():
            if h:
                d = {k.decode(): float(v) for k, v in h.items()}
                rows.append(
                    (
                        int(d.get("req", 0)),
                        int(d.get("err", 0)),
                        d.get("lat", 0.0),
                        d.get("max", 0.0),
                    )
                )
        return _summary(rows, minutes)

    async def errors(self, limit: int) -> list[dict[str, Any]]:
        return [json.loads(x) for x in await self.redis.lrange("mi:errors", 0, limit - 1)]
