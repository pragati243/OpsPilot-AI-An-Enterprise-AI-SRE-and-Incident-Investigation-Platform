import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.similarity import cosine_similarity
from app.models.memory import MemoryRecord, MemoryType
from app.repositories.memory_repository import MemoryRepository
from app.retrieval.embeddings import embed_query


async def recall_memories(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    query: str,
    memory_type: MemoryType | None = None,
    limit: int = 5,
) -> list[MemoryRecord]:
    """Authorization first, similarity second — never combined into one
    fuzzy score. `list_active` is the hard tenant/user/status filter; only
    records that already passed it are ranked for relevance at all, so a
    memory can never surface just because it's a close vector match.
    """
    candidates = await MemoryRepository(db).list_active(
        tenant_id=tenant_id, user_id=user_id, memory_type=memory_type
    )
    if not candidates:
        return []

    query_vector = await embed_query(query)
    scored = [
        (record, cosine_similarity(query_vector, record.embedding))
        for record in candidates
        if record.embedding is not None
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [record for record, _ in scored[:limit]]
