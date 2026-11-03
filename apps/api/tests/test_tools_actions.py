import pytest
from sqlalchemy import select

from app.guardrails.action_allowlist import ActionNotAllowedError
from app.guardrails.tool_policy import UnregisteredToolError, enforce_tool_policy
from app.models.incident import IncidentSeverity, IncidentStatus
from app.models.remediation import RemediationProposal, RemediationRiskLevel, RemediationStatus
from app.repositories.incident_repository import IncidentRepository
from app.tools.context import ToolContext
from app.tools.exceptions import IncidentNotFoundError
from app.tools.remediation import propose_remediation
from app.tools.reporting import create_incident_report
from app.tools.schemas import CreateIncidentReportInput, ProposeRemediationInput
from tests.conftest import create_tenant, create_user


async def _seed_incident(ctx: ToolContext, *, status=IncidentStatus.INVESTIGATING):
    return await IncidentRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        title="Checkout error rate elevated",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV2,
        status=status,
        created_by=ctx.user.id,
    )


async def test_create_incident_report_resolves_incident(tool_ctx: ToolContext) -> None:
    incident = await _seed_incident(tool_ctx)

    result = await create_incident_report(
        tool_ctx,
        CreateIncidentReportInput(
            incident_id=incident.id,
            diagnosis="Connection pool exhausted.",
            evidence={"metrics": {"error_rate_pct": 12.5}},
            resolution="Restarted the service and raised pool size.",
            outcome="resolved",
            confidence=0.9,
            citations=[],
        ),
    )

    assert result.incident_status == "resolved"
    refreshed = await IncidentRepository(tool_ctx.db).get_by_id(
        tenant_id=tool_ctx.tenant_id, incident_id=incident.id
    )
    assert refreshed is not None
    assert refreshed.status == IncidentStatus.RESOLVED
    assert refreshed.resolved_at is not None


async def test_create_incident_report_unresolved_keeps_investigating(
    tool_ctx: ToolContext,
) -> None:
    incident = await _seed_incident(tool_ctx)

    result = await create_incident_report(
        tool_ctx,
        CreateIncidentReportInput(
            incident_id=incident.id,
            diagnosis="Still gathering evidence, no root cause yet.",
            outcome="unresolved",
            confidence=0.2,
        ),
    )

    assert result.incident_status == "investigating"
    refreshed = await IncidentRepository(tool_ctx.db).get_by_id(
        tenant_id=tool_ctx.tenant_id, incident_id=incident.id
    )
    assert refreshed is not None
    assert refreshed.resolved_at is None


async def test_create_incident_report_unknown_incident_raises(tool_ctx: ToolContext) -> None:
    with pytest.raises(IncidentNotFoundError):
        await create_incident_report(
            tool_ctx,
            CreateIncidentReportInput(
                incident_id="00000000-0000-0000-0000-000000000000",
                diagnosis="n/a",
                outcome="unresolved",
                confidence=0.0,
            ),
        )


async def test_create_incident_report_cross_tenant_incident_raises(
    tool_ctx: ToolContext, db_session
) -> None:
    incident = await _seed_incident(tool_ctx)

    other_tenant = await create_tenant(db_session)
    other_user = await create_user(db_session, other_tenant)
    other_ctx = ToolContext(tenant_id=other_tenant.id, user=other_user, db=db_session)

    with pytest.raises(IncidentNotFoundError):
        await create_incident_report(
            other_ctx,
            CreateIncidentReportInput(
                incident_id=incident.id, diagnosis="n/a", outcome="unresolved", confidence=0.0
            ),
        )


async def test_propose_remediation_creates_pending_approval_proposal(
    tool_ctx: ToolContext,
) -> None:
    incident = await _seed_incident(tool_ctx)

    result = await propose_remediation(
        tool_ctx,
        ProposeRemediationInput(
            incident_id=incident.id,
            action_type="restart_service",
            action_params={"service": "checkout-service"},
            rationale="Clear stuck connections holding the pool.",
        ),
    )

    assert result.status == RemediationStatus.PENDING_APPROVAL
    assert result.requires_approval is True
    assert result.risk_level == RemediationRiskLevel.MEDIUM

    row = await tool_ctx.db.get(RemediationProposal, result.proposal_id)
    assert row is not None
    assert row.status == RemediationStatus.PENDING_APPROVAL


async def test_propose_remediation_rejects_action_outside_allowlist(
    tool_ctx: ToolContext,
) -> None:
    incident = await _seed_incident(tool_ctx)

    with pytest.raises(ActionNotAllowedError):
        await propose_remediation(
            tool_ctx,
            ProposeRemediationInput(
                incident_id=incident.id,
                action_type="drop_production_database",
                rationale="This should never be allowed.",
            ),
        )

    existing = await tool_ctx.db.scalar(
        select(RemediationProposal).where(RemediationProposal.incident_id == incident.id)
    )
    assert existing is None


async def test_propose_remediation_unknown_incident_raises(tool_ctx: ToolContext) -> None:
    with pytest.raises(IncidentNotFoundError):
        await propose_remediation(
            tool_ctx,
            ProposeRemediationInput(
                incident_id="00000000-0000-0000-0000-000000000000",
                action_type="restart_service",
                rationale="n/a",
            ),
        )


def test_enforce_tool_policy_rejects_unregistered_tool_name() -> None:
    with pytest.raises(UnregisteredToolError):
        enforce_tool_policy("not_a_real_tool")
