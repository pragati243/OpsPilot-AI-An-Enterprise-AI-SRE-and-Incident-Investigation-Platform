import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.remediation import RemediationRiskLevel, RemediationStatus


class RemediationProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    action_type: str
    action_params: dict
    rationale: str
    risk_level: RemediationRiskLevel
    status: RemediationStatus
    proposed_by: uuid.UUID | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


class ApproveRemediationRequest(BaseModel):
    action_params: dict | None = Field(
        default=None,
        description="If provided, the proposal is marked 'edited' rather than approved as-is.",
    )
