"""Hız sınırı: bellek içi ve Redis (MI_TEST_REDIS_URL varsa)."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from conftest import REDIS_URL
from mi_api.ratelimit import MemoryLimiter, RedisLimiter


async def test_memory_limiter_window() -> None:
    now = [0.0]
    limiter = MemoryLimiter(clock=lambda: now[0])
    assert [await limiter.allow("k", 3, 10) for _ in range(4)] == [True, True, True, False]
    now[0] = 10.5
    assert await limiter.allow("k", 3, 10)
    await limiter.reset("k")
    assert len(limiter.hits) == 0


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    if not REDIS_URL:
        pytest.skip("MI_TEST_REDIS_URL tanımlı değil")
    client = Redis.from_url(REDIS_URL)
    yield client
    await client.aclose()


async def test_redis_limiter_shared_between_instances(redis: Redis) -> None:
    key = f"test:{secrets.token_hex(4)}"
    a, b = RedisLimiter(redis), RedisLimiter(redis)
    assert await a.allow(key, 2, 60)
    assert await b.allow(key, 2, 60)
    assert not await a.allow(key, 2, 60)
    assert 0 < await redis.pttl("mi:rl:" + key) <= 60_000
    await a.reset(key)
    assert await b.allow(key, 2, 60)


async def test_redis_limiter_falls_back_when_unreachable() -> None:
    broken = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    limiter = RedisLimiter(broken)
    assert await limiter.allow("k", 1, 60)
    assert not await limiter.allow("k", 1, 60)
    await broken.aclose()
