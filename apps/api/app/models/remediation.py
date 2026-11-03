import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RemediationRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RemediationStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class RemediationProposal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A remediation action the agent proposed for an incident. Creating one
    never executes anything — it always starts PENDING_APPROVAL. Approval
    transitions (approve/edit/reject) are wired up when the workflow that
    consumes them lands.
    """

    __tablename__ = "remediation_proposals"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    action_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[RemediationRiskLevel] = mapped_column(
        SAEnum(RemediationRiskLevel, name="remediation_risk_level"), nullable=False
    )
    status: Mapped[RemediationStatus] = mapped_column(
        SAEnum(RemediationStatus, name="remediation_status"),
        nullable=False,
        default=RemediationStatus.PENDING_APPROVAL,
    )
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
