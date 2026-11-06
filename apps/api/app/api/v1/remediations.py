import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.remediation import RemediationProposal, RemediationStatus
from app.models.user import UserRole
from app.repositories.remediation_repository import RemediationRepository
from app.schemas.remediation import ApproveRemediationRequest, RemediationProposalRead

router = APIRouter(prefix="/remediations", tags=["remediations"])

# Approval is deliberately restricted — this is the human checkpoint the
# rest of the system relies on never being skippable. Admins and the
# dedicated "approver" role only; an SRE who merely requested an
# investigation can't also be the one who approves acting on it.
_require_approver = require_role(UserRole.ADMIN, UserRole.APPROVER)


async def _get_pending_proposal_or_404(
    db: AsyncSession, *, tenant_id: uuid.UUID, proposal_id: uuid.UUID
) -> RemediationProposal:
    proposal = await RemediationRepository(db).get_by_id(
        tenant_id=tenant_id, proposal_id=proposal_id
    )
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Remediation proposal not found"
        )
    if proposal.status != RemediationStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Proposal is already {proposal.status.value}, not pending",
        )
    return proposal


@router.get("/incident/{incident_id}", response_model=list[RemediationProposalRead])
async def list_remediations_for_incident(
    incident_id: uuid.UUID, db: DbSession, current_user: CurrentUser
) -> list[RemediationProposalRead]:
    proposals = await RemediationRepository(db).list_for_incident(
        tenant_id=current_user.tenant_id, incident_id=incident_id
    )
    return [RemediationProposalRead.model_validate(p) for p in proposals]


@router.post(
    "/{proposal_id}/approve",
    response_model=RemediationProposalRead,
    dependencies=[Depends(_require_approver)],
)
async def approve_remediation(
    proposal_id: uuid.UUID,
    payload: ApproveRemediationRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> RemediationProposalRead:
    proposal = await _get_pending_proposal_or_404(
        db, tenant_id=current_user.tenant_id, proposal_id=proposal_id
    )
    new_status = (
        RemediationStatus.EDITED
        if payload.action_params is not None
        else RemediationStatus.APPROVED
    )
    updated = await RemediationRepository(db).decide(
        proposal=proposal,
        status=new_status,
        decided_by=current_user.id,
        action_params=payload.action_params,
    )
    await db.commit()
    return RemediationProposalRead.model_validate(updated)


@router.post(
    "/{proposal_id}/reject",
    response_model=RemediationProposalRead,
    dependencies=[Depends(_require_approver)],
)
async def reject_remediation(
    proposal_id: uuid.UUID, db: DbSession, current_user: CurrentUser
) -> RemediationProposalRead:
    proposal = await _get_pending_proposal_or_404(
        db, tenant_id=current_user.tenant_id, proposal_id=proposal_id
    )
    updated = await RemediationRepository(db).decide(
        proposal=proposal, status=RemediationStatus.REJECTED, decided_by=current_user.id
    )
    await db.commit()
    return RemediationProposalRead.model_validate(updated)
