from app.models.document import DocumentSourceType
from app.models.episode import EpisodeOutcome
from app.models.incident import IncidentSeverity, IncidentStatus
from app.models.user import UserRole
from app.repositories.document_repository import DocumentRepository
from app.repositories.episode_repository import EpisodeRepository
from app.repositories.incident_repository import IncidentRepository
from app.tools.context import ToolContext
from app.tools.incidents import search_past_incidents
from app.tools.runbooks import search_runbooks
from app.tools.schemas import SearchPastIncidentsInput, SearchRunbooksInput
from tests.conftest import create_tenant, create_user


async def test_search_runbooks_matches_public_document(tool_ctx: ToolContext) -> None:
    await DocumentRepository(tool_ctx.db).create(
        tenant_id=tool_ctx.tenant_id,
        title="Diagnosing connection pool exhaustion",
        source_type=DocumentSourceType.RUNBOOK,
        content="Check QueuePool errors and restart the service as a stopgap.",
        access_scope=[],
        created_by=tool_ctx.user.id,
    )

    result = await search_runbooks(
        tool_ctx, SearchRunbooksInput(query="connection pool")
    )
    assert len(result.matches) == 1
    assert "connection pool" in result.matches[0].title.lower()


async def test_search_runbooks_hides_restricted_document_from_viewer(
    db_session,
) -> None:
    tenant = await create_tenant(db_session)
    viewer = await create_user(db_session, tenant, role=UserRole.VIEWER)
    admin = await create_user(db_session, tenant, role=UserRole.ADMIN)

    await DocumentRepository(db_session).create(
        tenant_id=tenant.id,
        title="Restricted failover procedure",
        source_type=DocumentSourceType.RUNBOOK,
        content="Only admins should run this.",
        access_scope=["admin", "approver"],
        created_by=admin.id,
    )

    viewer_ctx = ToolContext(tenant_id=tenant.id, user=viewer, db=db_session)
    admin_ctx = ToolContext(tenant_id=tenant.id, user=admin, db=db_session)

    viewer_result = await search_runbooks(
        viewer_ctx, SearchRunbooksInput(query="failover")
    )
    admin_result = await search_runbooks(
        admin_ctx, SearchRunbooksInput(query="failover")
    )

    assert viewer_result.matches == []
    assert len(admin_result.matches) == 1


async def test_search_runbooks_does_not_leak_across_tenants(
    tool_ctx: ToolContext, db_session
) -> None:
    await DocumentRepository(tool_ctx.db).create(
        tenant_id=tool_ctx.tenant_id,
        title="Tenant A runbook about memory leaks",
        source_type=DocumentSourceType.RUNBOOK,
        content="Tenant A specific content.",
        access_scope=[],
        created_by=tool_ctx.user.id,
    )

    other_tenant = await create_tenant(db_session)
    other_user = await create_user(db_session, other_tenant)
    other_ctx = ToolContext(tenant_id=other_tenant.id, user=other_user, db=db_session)

    result = await search_runbooks(other_ctx, SearchRunbooksInput(query="memory leaks"))
    assert result.matches == []


async def test_search_past_incidents_returns_diagnosis_and_resolution(
    tool_ctx: ToolContext,
) -> None:
    incident_repo = IncidentRepository(tool_ctx.db)
    incident = await incident_repo.create(
        tenant_id=tool_ctx.tenant_id,
        title="Checkout latency spike",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.RESOLVED,
        created_by=tool_ctx.user.id,
    )
    await EpisodeRepository(tool_ctx.db).create(
        tenant_id=tool_ctx.tenant_id,
        incident_id=incident.id,
        evidence={"metrics": {"latency_p99_ms": 4000}},
        diagnosis="Connection pool exhausted under peak load.",
        resolution="Restarted service and raised pool size.",
        outcome=EpisodeOutcome.RESOLVED,
        confidence=0.9,
    )

    result = await search_past_incidents(
        tool_ctx, SearchPastIncidentsInput(query="latency", service="checkout-service")
    )

    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.diagnosis == "Connection pool exhausted under peak load."
    assert match.outcome == EpisodeOutcome.RESOLVED


async def test_search_past_incidents_does_not_leak_across_tenants(
    tool_ctx: ToolContext, db_session
) -> None:
    await IncidentRepository(tool_ctx.db).create(
        tenant_id=tool_ctx.tenant_id,
        title="Tenant A incident",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV3,
        status=IncidentStatus.OPEN,
        created_by=tool_ctx.user.id,
    )

    other_tenant = await create_tenant(db_session)
    other_user = await create_user(db_session, other_tenant)
    other_ctx = ToolContext(tenant_id=other_tenant.id, user=other_user, db=db_session)

    result = await search_past_incidents(
        other_ctx, SearchPastIncidentsInput(query="Tenant A")
    )
    assert result.matches == []
