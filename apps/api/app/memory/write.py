import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.policy import SUPERSESSION_SIMILARITY_THRESHOLD, validate_content
from app.memory.similarity import cosine_similarity
from app.models.memory import MemoryProvenance, MemoryRecord, MemoryType
from app.repositories.memory_repository import MemoryRepository
from app.retrieval.embeddings import embed_passages


async def upsert_memory(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    memory_type: MemoryType,
    content: str,
    provenance: MemoryProvenance,
    confidence: float,
    source_episode_id: uuid.UUID | None = None,
) -> MemoryRecord:
    """Validate, embed, and store one memory, superseding an existing
    near-duplicate in the same scope rather than creating a redundant copy.
    Raises MemoryPolicyViolation if content fails the deterministic gate —
    callers decide whether that's fatal or just skip-and-log.
    """
    validate_content(content)
    (embedding,) = await embed_passages([content])

    repo = MemoryRepository(db)
    existing = await repo.list_active(
        tenant_id=tenant_id, user_id=user_id, memory_type=memory_type
    )
    # list_active with a user_id also returns tenant-shared rows (user_id is
    # None) — only compare against records in the *same* scope, so a
    # personal preference never supersedes a shared fact or vice versa.
    same_scope = [record for record in existing if record.user_id == user_id]

    conflicting = next(
        (
            record
            for record in same_scope
            if record.embedding is not None
            and cosine_similarity(embedding, record.embedding)
            >= SUPERSESSION_SIMILARITY_THRESHOLD
        ),
        None,
    )

    new_record = await repo.create(
        tenant_id=tenant_id,
        user_id=user_id,
        memory_type=memory_type,
        content=content,
        provenance=provenance,
        confidence=confidence,
        source_episode_id=source_episode_id,
        embedding=embedding,
    )
    if conflicting is not None:
        await repo.supersede(old=conflicting, new=new_record)

    return new_record
