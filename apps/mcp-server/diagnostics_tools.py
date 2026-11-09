from typing import Annotated, Any

import bootstrap  # noqa: F401  — must run before any `app.*` import below
from auth import call_tool_fn
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from app.tools.health import get_service_health as _get_service_health
from app.tools.logs import query_logs as _query_logs
from app.tools.metrics import get_service_metrics as _get_service_metrics
from app.tools.schemas import (
    GetServiceHealthInput,
    GetServiceMetricsInput,
    LogSeverity,
    QueryLogsInput,
)


def register(server: MCPServer) -> None:
    """Registers the 3 pure-diagnostic read-only tools. Each one is a thin
    wrapper: build the same Pydantic input apps/api's HTTP layer builds,
    hand it to the existing tool function alongside an authenticated
    ToolContext, return the result as a dict. No diagnostic logic lives
    here — it all stays in apps/api/app/tools/.
    """

    @server.tool(
        description="Get the current health status and a symptom-level summary for a service."
    )
    async def get_service_health(
        service: str, environment: str = "production", *, ctx: Context
    ) -> dict[str, Any]:
        return await call_tool_fn(
            ctx,
            _get_service_health,
            GetServiceHealthInput(service=service, environment=environment),
        )

    @server.tool(
        description=(
            "Query recent logs for a service, filtered by a minimum severity "
            "(debug/info/warn/error/critical). time_window looks like '15m', '1h', or '2d'."
        )
    )
    async def query_logs(
        service: str,
        environment: str = "production",
        time_window: str = "15m",
        min_severity: LogSeverity = LogSeverity.WARN,
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        return await call_tool_fn(
            ctx,
            _query_logs,
            QueryLogsInput(
                service=service,
                environment=environment,
                time_window=time_window,
                min_severity=min_severity,
                limit=limit,
            ),
        )

    @server.tool(
        description=(
            "Get latency (p50/p95/p99), error rate, request rate, cpu, and memory for a "
            "service over a time window like '15m', '1h', or '2d'."
        )
    )
    async def get_service_metrics(
        service: str,
        environment: str = "production",
        time_window: str = "15m",
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        return await call_tool_fn(
            ctx,
            _get_service_metrics,
            GetServiceMetricsInput(
                service=service, environment=environment, time_window=time_window
            ),
        )
