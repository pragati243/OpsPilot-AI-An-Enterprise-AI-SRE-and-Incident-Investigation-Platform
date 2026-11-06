from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status

from app.api.deps import CurrentUser
from app.core.redis_client import get_redis_client


class RateLimitExceeded(HTTPException):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded, try again later.",
            headers={"Retry-After": str(retry_after_seconds)},
        )


async def check_rate_limit(*, key: str, limit: int, window_seconds: int) -> None:
    """Fixed-window counter in Redis via INCR+EXPIRE. Not a precise sliding
    window — a client right at a window boundary could get marginally more
    than `limit` requests through — an acceptable trade for the simplicity
    here; this is abuse prevention, not a billing meter.
    """
    redis = get_redis_client()
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window_seconds)
    if current > limit:
        ttl = await redis.ttl(key)
        raise RateLimitExceeded(retry_after_seconds=max(ttl, 1))


def rate_limit_by_user(
    *, limit: int, window_seconds: int, scope: str
) -> Callable[[CurrentUser], Awaitable[None]]:
    """Rate limit an authenticated endpoint per user. Must come after auth
    in the route's dependency list — it depends on CurrentUser already
    having been resolved.
    """

    async def _dependency(current_user: CurrentUser) -> None:
        key = f"ratelimit:{scope}:user:{current_user.id}"
        await check_rate_limit(key=key, limit=limit, window_seconds=window_seconds)

    return _dependency


def rate_limit_by_client(
    *, limit: int, window_seconds: int, scope: str
) -> Callable[[Request], Awaitable[None]]:
    """Rate limit an unauthenticated endpoint (login, register) by client
    IP — there's no user identity yet to key on.
    """

    async def _dependency(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        key = f"ratelimit:{scope}:ip:{client_host}"
        await check_rate_limit(key=key, limit=limit, window_seconds=window_seconds)

    return _dependency
