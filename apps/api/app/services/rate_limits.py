from __future__ import annotations

import time
from collections import defaultdict
from typing import Protocol

import redis.asyncio as redis


class RateLimitExceeded(Exception):
    """Raised when a request bucket has exhausted its allowance."""


class RateLimiter(Protocol):
    async def check(self, key: str, *, limit: int, window_seconds: int) -> None: ...


class DeterministicRateLimiter:
    """In-memory fixed-window limiter with an explicitly controlled test clock."""

    def __init__(self) -> None:
        self._now = 0.0
        self._buckets: dict[tuple[str, int], int] = defaultdict(int)

    def advance(self, seconds: float) -> None:
        self._now += seconds

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        window = int(self._now // window_seconds)
        bucket = (key, window)
        self._buckets[bucket] += 1
        if self._buckets[bucket] > limit:
            raise RateLimitExceeded


class RedisRateLimiter:
    """Redis fixed-window limiter; Redis failure is intentionally fail-closed."""

    def __init__(self, redis_url: str, *, prefix: str = "visualops:rate") -> None:
        self._client = redis.from_url(redis_url)
        self._prefix = prefix

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        window = int(time.time() // window_seconds)
        redis_key = f"{self._prefix}:{window}:{key}"
        pipeline = self._client.pipeline(transaction=True)
        pipeline.incr(redis_key)
        pipeline.expire(redis_key, window_seconds + 1)
        count, _ = await pipeline.execute()
        if int(count) > limit:
            raise RateLimitExceeded

    async def close(self) -> None:
        await self._client.aclose()
