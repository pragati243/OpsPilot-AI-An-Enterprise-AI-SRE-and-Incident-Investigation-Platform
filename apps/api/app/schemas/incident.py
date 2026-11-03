import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import InvestigationReport
from app.models.incident import IncidentSeverity, IncidentStatus


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    service: str = Field(min_length=1, max_length=150)
    environment: str = "production"
    severity: IncidentSeverity


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    service: str
    environment: str
    severity: IncidentSeverity
    status: IncidentStatus
    created_at: datetime
    resolved_at: datetime | None


class InvestigateResponse(BaseModel):
    incident_id: uuid.UUID
    report: InvestigationReport
