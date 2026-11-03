from datetime import UTC, datetime

import pytest

from app.models.service import ServiceStatus
from app.repositories.service_repository import ServiceRepository
from app.tools.context import ToolContext
from app.tools.exceptions import ServiceNotFoundError
from app.tools.health import get_service_health
from app.tools.logs import query_logs
from app.tools.metrics import get_service_metrics
from app.tools.schemas import (
    GetServiceHealthInput,
    GetServiceMetricsInput,
    LogSeverity,
    QueryLogsInput,
)
from app.tools.time_window import InvalidTimeWindowError
from tests.conftest import create_tenant, create_user

FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


async def _seed_service(
    ctx: ToolContext,
    *,
    name: str = "checkout-service",
    status: ServiceStatus = ServiceStatus.DEGRADED,
    scenario_tag: str = "db_connection_pool_exhaustion",
):
    return await ServiceRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        name=name,
        environment="production",
        description="test service",
        owner_team="test-team",
        status=status,
        scenario_tag=scenario_tag,
    )


async def test_get_service_health_returns_status_and_summary(tool_ctx: ToolContext) -> None:
    await _seed_service(tool_ctx)
    result = await get_service_health(tool_ctx, GetServiceHealthInput(service="checkout-service"))
    assert result.status == ServiceStatus.DEGRADED
    assert result.summary


async def test_get_service_health_unknown_service_raises(tool_ctx: ToolContext) -> None:
    with pytest.raises(ServiceNotFoundError):
        await get_service_health(tool_ctx, GetServiceHealthInput(service="does-not-exist"))


async def test_get_service_health_cross_tenant_is_not_found(
    tool_ctx: ToolContext, db_session
) -> None:
    await _seed_service(tool_ctx)

    other_tenant = await create_tenant(db_session)
    other_user = await create_user(db_session, other_tenant)
    other_ctx = ToolContext(tenant_id=other_tenant.id, user=other_user, db=db_session)

    with pytest.raises(ServiceNotFoundError):
        await get_service_health(other_ctx, GetServiceHealthInput(service="checkout-service"))


async def test_query_logs_filters_by_min_severity(tool_ctx: ToolContext) -> None:
    await _seed_service(tool_ctx)
    result = await query_logs(
        tool_ctx,
        QueryLogsInput(
            service="checkout-service",
            time_window="30m",
            min_severity=LogSeverity.ERROR,
            limit=50,
        ),
        now=FIXED_NOW,
    )
    assert result.entries
    assert all(e.severity in (LogSeverity.ERROR, LogSeverity.CRITICAL) for e in result.entries)


async def test_query_logs_is_deterministic_for_the_same_clock(tool_ctx: ToolContext) -> None:
    await _seed_service(tool_ctx)
    params = QueryLogsInput(service="checkout-service")
    first = await query_logs(tool_ctx, params, now=FIXED_NOW)
    second = await query_logs(tool_ctx, params, now=FIXED_NOW)
    assert first == second


async def test_query_logs_rejects_invalid_time_window(tool_ctx: ToolContext) -> None:
    await _seed_service(tool_ctx)
    with pytest.raises(InvalidTimeWindowError):
        await query_logs(
            tool_ctx,
            QueryLogsInput(service="checkout-service", time_window="not-a-window"),
            now=FIXED_NOW,
        )


async def test_query_logs_unknown_service_raises(tool_ctx: ToolContext) -> None:
    with pytest.raises(ServiceNotFoundError):
        await query_logs(
            tool_ctx, QueryLogsInput(service="does-not-exist"), now=FIXED_NOW
        )


async def test_get_service_metrics_reflects_degraded_scenario(tool_ctx: ToolContext) -> None:
    await _seed_service(tool_ctx)
    await _seed_service(
        tool_ctx, name="api-gateway", status=ServiceStatus.HEALTHY, scenario_tag="healthy"
    )

    degraded = await get_service_metrics(
        tool_ctx, GetServiceMetricsInput(service="checkout-service"), now=FIXED_NOW
    )
    healthy = await get_service_metrics(
        tool_ctx, GetServiceMetricsInput(service="api-gateway"), now=FIXED_NOW
    )

    assert degraded.error_rate_pct > healthy.error_rate_pct
    assert degraded.latency_p99_ms > healthy.latency_p99_ms


async def test_get_service_metrics_is_deterministic_for_the_same_clock(
    tool_ctx: ToolContext,
) -> None:
    await _seed_service(tool_ctx)
    params = GetServiceMetricsInput(service="checkout-service")
    first = await get_service_metrics(tool_ctx, params, now=FIXED_NOW)
    second = await get_service_metrics(tool_ctx, params, now=FIXED_NOW)
    assert first == second
