import functools
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import ParamSpec, TypeVar

from app.core.logging import get_logger
from app.tools.context import ToolContext

logger = get_logger(__name__)


class ToolAccessMode(StrEnum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    access_mode: ToolAccessMode


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "get_service_health": ToolSpec("get_service_health", ToolAccessMode.READ_ONLY),
    "query_logs": ToolSpec("query_logs", ToolAccessMode.READ_ONLY),
    "get_service_metrics": ToolSpec("get_service_metrics", ToolAccessMode.READ_ONLY),
    "search_runbooks": ToolSpec("search_runbooks", ToolAccessMode.READ_ONLY),
    "search_past_incidents": ToolSpec("search_past_incidents", ToolAccessMode.READ_ONLY),
    "create_incident_report": ToolSpec("create_incident_report", ToolAccessMode.MUTATING),
    "propose_remediation": ToolSpec("propose_remediation", ToolAccessMode.MUTATING),
}


class UnregisteredToolError(Exception):
    pass


P = ParamSpec("P")
R = TypeVar("R")


def enforce_tool_policy(
    tool_name: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Wrap a tool function so every call is checked against the tool
    registry and logged with outcome + latency — the audit trail guardrails
    need regardless of which caller (API route today, a LangGraph tool node
    later) invokes the tool.

    This does not do RBAC on its own: `create_incident_report` and
    `propose_remediation` are reachable by any authenticated tenant member
    today. Role-gating specific tools is a one-line addition to TOOL_REGISTRY
    once a concrete need shows up — not worth a knob with no caller yet.
    """
    if tool_name not in TOOL_REGISTRY:
        raise UnregisteredToolError(
            f"{tool_name!r} is not in TOOL_REGISTRY; every tool must be registered "
            "with an explicit access mode before it can be called"
        )
    spec = TOOL_REGISTRY[tool_name]

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            ctx = _find_tool_context(args, kwargs)
            started = time.monotonic()
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                logger.warning(
                    "tool_call_failed",
                    tool=spec.name,
                    access_mode=spec.access_mode.value,
                    tenant_id=str(ctx.tenant_id) if ctx else None,
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                    error_type=type(exc).__name__,
                )
                raise
            logger.info(
                "tool_call_succeeded",
                tool=spec.name,
                access_mode=spec.access_mode.value,
                tenant_id=str(ctx.tenant_id) if ctx else None,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return result

        return wrapper

    return decorator


def _find_tool_context(args: tuple, kwargs: dict) -> ToolContext | None:
    for value in (*args, *kwargs.values()):
        if isinstance(value, ToolContext):
            return value
    return None
