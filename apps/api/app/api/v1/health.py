from typing import Any

from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    """Liveness probe: process is up. No dependency checks."""
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(db: DbSession, response: Response) -> dict[str, Any]:
    """Readiness probe: can this instance actually serve traffic."""
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        checks["database"] = f"error: {exc}"

    settings = get_settings()
    redis_client: Redis = Redis.from_url(settings.redis_url)
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"
    finally:
        await redis_client.aclose()

    is_healthy = all(value == "ok" for value in checks.values())
    response.status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if is_healthy else "degraded", "checks": checks}
