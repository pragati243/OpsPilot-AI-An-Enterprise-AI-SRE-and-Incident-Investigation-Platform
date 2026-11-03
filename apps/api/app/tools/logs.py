from datetime import UTC, datetime

from app.guardrails.tool_policy import enforce_tool_policy
from app.repositories.service_repository import ServiceRepository
from app.tools.context import ToolContext
from app.tools.exceptions import ServiceNotFoundError
from app.tools.schemas import QueryLogsInput, QueryLogsResult
from app.tools.simulator.generator import generate_logs
from app.tools.time_window import parse_time_window


@enforce_tool_policy("query_logs")
async def query_logs(
    ctx: ToolContext, params: QueryLogsInput, *, now: datetime | None = None
) -> QueryLogsResult:
    service = await ServiceRepository(ctx.db).get_by_name(
        tenant_id=ctx.tenant_id, name=params.service, environment=params.environment
    )
    if service is None:
        raise ServiceNotFoundError(params.service)

    window = parse_time_window(params.time_window)
    entries, total_matched, truncated = generate_logs(
        service,
        window,
        now or datetime.now(UTC),
        min_severity=params.min_severity,
        limit=params.limit,
        time_window_label=params.time_window,
    )
    return QueryLogsResult(
        service=service.name,
        time_window=params.time_window,
        entries=entries,
        total_matched=total_matched,
        truncated=truncated,
    )
