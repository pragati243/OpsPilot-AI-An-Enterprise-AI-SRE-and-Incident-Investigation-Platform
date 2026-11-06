import uuid

import pytest

from app.core.rate_limit import RateLimitExceeded, check_rate_limit
from app.core.redis_client import get_redis_client


def _unique_key() -> str:
    return f"ratelimit:test:{uuid.uuid4().hex}"


async def test_check_rate_limit_allows_up_to_the_limit() -> None:
    key = _unique_key()
    for _ in range(3):
        await check_rate_limit(key=key, limit=3, window_seconds=5)


async def test_check_rate_limit_blocks_once_limit_exceeded() -> None:
    key = _unique_key()
    for _ in range(3):
        await check_rate_limit(key=key, limit=3, window_seconds=5)

    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_rate_limit(key=key, limit=3, window_seconds=5)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers
    assert int(exc_info.value.headers["Retry-After"]) >= 1


async def test_check_rate_limit_resets_after_the_window() -> None:
    key = _unique_key()
    for _ in range(2):
        await check_rate_limit(key=key, limit=2, window_seconds=1)

    with pytest.raises(RateLimitExceeded):
        await check_rate_limit(key=key, limit=2, window_seconds=1)

    redis = get_redis_client()
    await redis.delete(key)  # simulate the window having elapsed, without a real sleep

    await check_rate_limit(key=key, limit=2, window_seconds=1)
