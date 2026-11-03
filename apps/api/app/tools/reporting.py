from datetime import UTC, datetime

from app.guardrails.tool_policy import enforce_tool_policy
from app.models.episode import EpisodeOutcome
from app.models.incident import IncidentStatus
from app.repositories.episode_repository import EpisodeRepository
from app.repositories.incident_repository import IncidentRepository
from app.tools.context import ToolContext
from app.tools.exceptions import IncidentNotFoundError
from app.tools.schemas import CreateIncidentReportInput, CreateIncidentReportResult

_STATUS_FOR_OUTCOME = {
    EpisodeOutcome.RESOLVED: IncidentStatus.RESOLVED,
    EpisodeOutcome.UNRESOLVED: IncidentStatus.INVESTIGATING,
    EpisodeOutcome.ESCALATED: IncidentStatus.INVESTIGATING,
}


@enforce_tool_policy("create_incident_report")
async def create_incident_report(
    ctx: ToolContext, params: CreateIncidentReportInput
) -> CreateIncidentReportResult:
    incident_repo = IncidentRepository(ctx.db)
    incident = await incident_repo.get_by_id(
        tenant_id=ctx.tenant_id, incident_id=params.incident_id
    )
    if incident is None:
        raise IncidentNotFoundError(str(params.incident_id))

    episode = await EpisodeRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        incident_id=incident.id,
        evidence=params.evidence,
        diagnosis=params.diagnosis,
        resolution=params.resolution,
        outcome=params.outcome,
        confidence=params.confidence,
    )

    new_status = _STATUS_FOR_OUTCOME[params.outcome]
    resolved_at = datetime.now(UTC) if new_status == IncidentStatus.RESOLVED else None
    await incident_repo.update_status(
        incident=incident, status=new_status, resolved_at=resolved_at
    )

    return CreateIncidentReportResult(
        episode_id=episode.id,
        incident_id=incident.id,
        incident_status=new_status.value,
    )
