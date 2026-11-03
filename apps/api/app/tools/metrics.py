from datetime import UTC, datetime

from app.guardrails.tool_policy import enforce_tool_policy
from app.repositories.service_repository import ServiceRepository
from app.tools.context import ToolContext
from app.tools.exceptions import ServiceNotFoundError
from app.tools.schemas import GetServiceMetricsInput, MetricsSnapshot
from app.tools.simulator.generator import generate_metrics
from app.tools.time_window import parse_time_window


@enforce_tool_policy("get_service_metrics")
async def get_service_metrics(
    ctx: ToolContext, params: GetServiceMetricsInput, *, now: datetime | None = None
) -> MetricsSnapshot:
    service = await ServiceRepository(ctx.db).get_by_name(
        tenant_id=ctx.tenant_id, name=params.service, environment=params.environment
    )
    if service is None:
        raise ServiceNotFoundError(params.service)

    window = parse_time_window(params.time_window)
    return generate_metrics(
        service, window, now or datetime.now(UTC), time_window_label=params.time_window
    )
