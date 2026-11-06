from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    """One connection pool per process. Rate limiting is the first
    consumer; response caching is the obvious next one.
    """
    return Redis.from_url(get_settings().redis_url, decode_responses=True)
