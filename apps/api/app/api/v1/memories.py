import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.memory.policy import MemoryPolicyViolation, check_profile_ownership, validate_content
from app.memory.schemas import CorrectMemoryRequest, MemoryRecordRead, SetProfilePreferenceRequest
from app.memory.write import upsert_memory
from app.models.memory import MemoryProvenance, MemoryRecord, MemoryType
from app.models.user import User
from app.repositories.memory_repository import MemoryRepository
from app.retrieval.embeddings import embed_passages

router = APIRouter(prefix="/memories", tags=["memories"])


def _ensure_visible_and_owned(record: MemoryRecord, current_user: User) -> None:
    if record.user_id is not None and record.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify another user's memory"
        )


@router.get("", response_model=list[MemoryRecordRead])
async def list_memories(db: DbSession, current_user: CurrentUser) -> list[MemoryRecordRead]:
    """Tenant-shared memories plus this user's own profile memories — never
    another user's. This is the "inspect your memories" half of the spec's
    inspect/correct/delete requirement.
    """
    records = await MemoryRepository(db).list_active(
        tenant_id=current_user.tenant_id, user_id=current_user.id
    )
    return [MemoryRecordRead.model_validate(record) for record in records]


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, db: DbSession, current_user: CurrentUser
) -> None:
    repo = MemoryRepository(db)
    record = await repo.get_by_id(tenant_id=current_user.tenant_id, memory_id=memory_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    _ensure_visible_and_owned(record, current_user)
    await repo.soft_delete(record=record)
    await db.commit()


@router.patch("/{memory_id}", response_model=MemoryRecordRead)
async def correct_memory(
    memory_id: uuid.UUID,
    payload: CorrectMemoryRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> MemoryRecordRead:
    """A correction always supersedes the specific record being corrected —
    unlike extraction/profile-setting, it doesn't go looking for *some*
    similar record to replace; the target is already named in the URL.
    """
    repo = MemoryRepository(db)
    record = await repo.get_by_id(tenant_id=current_user.tenant_id, memory_id=memory_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    _ensure_visible_and_owned(record, current_user)

    try:
        validate_content(payload.content)
    except MemoryPolicyViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    (embedding,) = await embed_passages([payload.content])
    new_record = await repo.create(
        tenant_id=current_user.tenant_id,
        user_id=record.user_id,
        memory_type=record.memory_type,
        content=payload.content,
        provenance=MemoryProvenance.USER_CONFIRMED,
        confidence=1.0,
        source_episode_id=record.source_episode_id,
        embedding=embedding,
    )
    await repo.supersede(old=record, new=new_record)
    await db.commit()
    return MemoryRecordRead.model_validate(new_record)


@router.put("/profile", response_model=MemoryRecordRead)
async def set_profile_preference(
    payload: SetProfilePreferenceRequest, db: DbSession, current_user: CurrentUser
) -> MemoryRecordRead:
    """Profile memory is explicitly stated, never inferred — there's no
    chat/feedback signal yet to extract it from, so this is the one write
    path for it (the worked example in the spec: "prefers concise reports
    with evidence first").
    """
    check_profile_ownership(target_user_id=current_user.id, actor_user_id=current_user.id)
    try:
        record = await upsert_memory(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            memory_type=MemoryType.PROFILE,
            content=payload.content,
            provenance=MemoryProvenance.USER_CONFIRMED,
            confidence=1.0,
        )
    except MemoryPolicyViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    await db.commit()
    return MemoryRecordRead.model_validate(record)
