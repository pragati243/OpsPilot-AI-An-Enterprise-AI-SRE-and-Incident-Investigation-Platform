from app.guardrails.tool_policy import enforce_tool_policy
from app.repositories.service_repository import ServiceRepository
from app.tools.context import ToolContext
from app.tools.exceptions import ServiceNotFoundError
from app.tools.schemas import GetServiceHealthInput, ServiceHealthResult
from app.tools.simulator.scenarios import get_scenario


@enforce_tool_policy("get_service_health")
async def get_service_health(
    ctx: ToolContext, params: GetServiceHealthInput
) -> ServiceHealthResult:
    service = await ServiceRepository(ctx.db).get_by_name(
        tenant_id=ctx.tenant_id, name=params.service, environment=params.environment
    )
    if service is None:
        raise ServiceNotFoundError(params.service)

    scenario = get_scenario(service.scenario_tag)
    return ServiceHealthResult(
        service=service.name,
        environment=service.environment,
        status=service.status,
        summary=scenario.summary,
    )
