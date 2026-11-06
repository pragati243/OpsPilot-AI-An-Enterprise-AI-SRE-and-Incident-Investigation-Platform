import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.remediation import RemediationProposal, RemediationRiskLevel, RemediationStatus


class RemediationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, *, tenant_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> RemediationProposal | None:
        result = await self._session.execute(
            select(RemediationProposal).where(
                RemediationProposal.tenant_id == tenant_id,
                RemediationProposal.id == proposal_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_incident(
        self, *, tenant_id: uuid.UUID, incident_id: uuid.UUID
    ) -> list[RemediationProposal]:
        result = await self._session.execute(
            select(RemediationProposal)
            .where(
                RemediationProposal.tenant_id == tenant_id,
                RemediationProposal.incident_id == incident_id,
            )
            .order_by(RemediationProposal.created_at.desc())
        )
        return list(result.scalars().all())

    async def decide(
        self,
        *,
        proposal: RemediationProposal,
        status: RemediationStatus,
        decided_by: uuid.UUID,
        action_params: dict | None = None,
    ) -> RemediationProposal:
        proposal.status = status
        proposal.decided_by = decided_by
        proposal.decided_at = datetime.now(UTC)
        if action_params is not None:
            proposal.action_params = action_params
        await self._session.flush()
        return proposal

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        action_type: str,
        action_params: dict,
        rationale: str,
        risk_level: RemediationRiskLevel,
        proposed_by: uuid.UUID | None,
    ) -> RemediationProposal:
        proposal = RemediationProposal(
            tenant_id=tenant_id,
            incident_id=incident_id,
            action_type=action_type,
            action_params=action_params,
            rationale=rationale,
            risk_level=risk_level,
            status=RemediationStatus.PENDING_APPROVAL,
            proposed_by=proposed_by,
        )
        self._session.add(proposal)
        await self._session.flush()
        return proposal
