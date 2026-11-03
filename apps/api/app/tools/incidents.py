from app.guardrails.tool_policy import enforce_tool_policy
from app.repositories.episode_repository import EpisodeRepository
from app.repositories.incident_repository import IncidentRepository
from app.tools.context import ToolContext
from app.tools.schemas import PastIncidentMatch, SearchPastIncidentsInput, SearchPastIncidentsResult


@enforce_tool_policy("search_past_incidents")
async def search_past_incidents(
    ctx: ToolContext, params: SearchPastIncidentsInput
) -> SearchPastIncidentsResult:
    incidents = await IncidentRepository(ctx.db).search(
        tenant_id=ctx.tenant_id, query=params.query, service=params.service, limit=params.limit
    )

    episode_repo = EpisodeRepository(ctx.db)
    matches = []
    for rank, incident in enumerate(incidents):
        episode = await episode_repo.get_latest_for_incident(
            tenant_id=ctx.tenant_id, incident_id=incident.id
        )
        matches.append(
            PastIncidentMatch(
                incident_id=incident.id,
                title=incident.title,
                service=incident.service,
                severity=incident.severity.value,
                status=incident.status.value,
                diagnosis=episode.diagnosis if episode else None,
                resolution=episode.resolution if episode else None,
                outcome=episode.outcome if episode else None,
                created_at=incident.created_at,
                score=float(len(incidents) - rank),
            )
        )
    return SearchPastIncidentsResult(query=params.query, matches=matches)
