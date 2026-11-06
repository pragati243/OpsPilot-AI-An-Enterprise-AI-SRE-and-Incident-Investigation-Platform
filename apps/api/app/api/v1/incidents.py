import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agents.graph import InvestigationIncomplete, run_investigation, stream_investigation
from app.api.deps import AgentLLMDep, CurrentUser, DbSession
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit_by_user
from app.models.incident import IncidentStatus
from app.repositories.incident_repository import IncidentRepository
from app.schemas.incident import IncidentCreate, IncidentRead, InvestigateResponse
from app.tools.context import ToolContext

logger = get_logger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])

_investigate_rate_limit = Depends(
    rate_limit_by_user(limit=10, window_seconds=60, scope="investigate")
)


@router.post("", response_model=IncidentRead, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate, db: DbSession, current_user: CurrentUser
) -> IncidentRead:
    incident = await IncidentRepository(db).create(
        tenant_id=current_user.tenant_id,
        title=payload.title,
        service=payload.service,
        environment=payload.environment,
        severity=payload.severity,
        status=IncidentStatus.OPEN,
        created_by=current_user.id,
    )
    await db.commit()
    return IncidentRead.model_validate(incident)


@router.get("", response_model=list[IncidentRead])
async def list_incidents(db: DbSession, current_user: CurrentUser) -> list[IncidentRead]:
    incidents = await IncidentRepository(db).search(
        tenant_id=current_user.tenant_id, query="", service=None, limit=50
    )
    return [IncidentRead.model_validate(incident) for incident in incidents]


@router.get("/{incident_id}", response_model=IncidentRead)
async def get_incident(
    incident_id: uuid.UUID, db: DbSession, current_user: CurrentUser
) -> IncidentRead:
    incident = await IncidentRepository(db).get_by_id(
        tenant_id=current_user.tenant_id, incident_id=incident_id
    )
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return IncidentRead.model_validate(incident)


@router.post(
    "/{incident_id}/investigate",
    response_model=InvestigateResponse,
    dependencies=[_investigate_rate_limit],
)
async def investigate_incident(
    incident_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
    llm: AgentLLMDep,
) -> InvestigateResponse:
    ctx = ToolContext(tenant_id=current_user.tenant_id, user=current_user, db=db)
    try:
        report = await run_investigation(ctx, incident_id, llm)
    except InvestigationIncomplete as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.reason) from exc
    except Exception as exc:
        # Fallback: the dominant external dependency here is the LLM API.
        # Whatever broke, the caller gets a clean, actionable response —
        # never a raw 500 with internal details leaked.
        logger.error(
            "investigation_failed_unexpectedly", incident_id=str(incident_id), exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation service temporarily unavailable, please try again shortly.",
        ) from exc
    await db.commit()
    return InvestigateResponse(incident_id=incident_id, report=report)


@router.post("/{incident_id}/investigate/stream", dependencies=[_investigate_rate_limit])
async def investigate_incident_stream(
    incident_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
    llm: AgentLLMDep,
) -> StreamingResponse:
    """Same investigation, streamed as Server-Sent Events: a `node_complete`
    event per LangGraph node as it finishes, then one terminal `report` or
    `error` event. Deliberately POST rather than a GET+EventSource — this
    needs the normal Authorization header, which EventSource can't send.
    """
    ctx = ToolContext(tenant_id=current_user.tenant_id, user=current_user, db=db)

    async def event_stream():
        try:
            async for event in stream_investigation(ctx, incident_id, llm):
                yield f"event: {event.event}\ndata: {json.dumps(event.data)}\n\n"
                if event.event in ("report", "error"):
                    if event.event == "report":
                        await db.commit()
                    return
        except Exception:
            logger.error(
                "investigation_stream_failed_unexpectedly",
                incident_id=str(incident_id),
                exc_info=True,
            )
            yield (
                "event: error\n"
                f"data: {json.dumps({'message': 'investigation failed unexpectedly'})}\n\n"
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
