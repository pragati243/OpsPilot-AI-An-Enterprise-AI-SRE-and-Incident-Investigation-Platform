import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.remediation import RemediationProposal, RemediationRiskLevel, RemediationStatus


class RemediationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
