from app.guardrails.action_allowlist import check_action_allowed
from app.guardrails.tool_policy import enforce_tool_policy
from app.models.remediation import RemediationStatus
from app.repositories.incident_repository import IncidentRepository
from app.repositories.remediation_repository import RemediationRepository
from app.tools.context import ToolContext
from app.tools.exceptions import IncidentNotFoundError
from app.tools.schemas import ProposeRemediationInput, ProposeRemediationResult


@enforce_tool_policy("propose_remediation")
async def propose_remediation(
    ctx: ToolContext, params: ProposeRemediationInput
) -> ProposeRemediationResult:
    """Never executes anything. Validates the action type against the
    allowlist (raises ActionNotAllowedError otherwise) and persists a
    PENDING_APPROVAL proposal — the model can suggest a remediation, it
    cannot grant itself permission to run it.
    """
    incident = await IncidentRepository(ctx.db).get_by_id(
        tenant_id=ctx.tenant_id, incident_id=params.incident_id
    )
    if incident is None:
        raise IncidentNotFoundError(str(params.incident_id))

    allowed_action = check_action_allowed(params.action_type)

    proposal = await RemediationRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        incident_id=incident.id,
        action_type=params.action_type,
        action_params=params.action_params,
        rationale=params.rationale,
        risk_level=allowed_action.risk_level,
        proposed_by=ctx.user.id,
    )

    return ProposeRemediationResult(
        proposal_id=proposal.id,
        incident_id=incident.id,
        action_type=proposal.action_type,
        risk_level=proposal.risk_level,
        status=RemediationStatus.PENDING_APPROVAL,
        requires_approval=True,
    )
