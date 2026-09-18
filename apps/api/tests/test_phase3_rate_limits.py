from __future__ import annotations

import pytest

from app.services.rate_limits import DeterministicRateLimiter, RateLimitExceeded


@pytest.mark.anyio
async def test_deterministic_limiter_enforces_independent_buckets() -> None:
    limiter = DeterministicRateLimiter()
    await limiter.check("credential:a", limit=2, window_seconds=60)
    await limiter.check("credential:a", limit=2, window_seconds=60)
    await limiter.check("credential:b", limit=2, window_seconds=60)

    with pytest.raises(RateLimitExceeded):
        await limiter.check("credential:a", limit=2, window_seconds=60)

    limiter.advance(60)
    await limiter.check("credential:a", limit=2, window_seconds=60)
