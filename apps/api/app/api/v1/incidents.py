import uuid

from fastapi import APIRouter, HTTPException, status

from app.agents.graph import InvestigationIncomplete, run_investigation
from app.api.deps import AgentLLMDep, CurrentUser, DbSession
from app.models.incident import IncidentStatus
from app.repositories.incident_repository import IncidentRepository
from app.schemas.incident import IncidentCreate, IncidentRead, InvestigateResponse
from app.tools.context import ToolContext

router = APIRouter(prefix="/incidents", tags=["incidents"])


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


@router.post("/{incident_id}/investigate", response_model=InvestigateResponse)
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
    await db.commit()
    return InvestigateResponse(incident_id=incident_id, report=report)
