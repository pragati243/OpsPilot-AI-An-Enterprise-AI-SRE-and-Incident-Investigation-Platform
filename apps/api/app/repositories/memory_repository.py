import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryProvenance, MemoryRecord, MemoryStatus, MemoryType


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, *, tenant_id: uuid.UUID, memory_id: uuid.UUID
    ) -> MemoryRecord | None:
        result = await self._session.execute(
            select(MemoryRecord).where(
                MemoryRecord.tenant_id == tenant_id, MemoryRecord.id == memory_id
            )
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        memory_type: MemoryType | None = None,
    ) -> list[MemoryRecord]:
        """Tenant-scoped (shared) memories are always included; pass
        `user_id` to also include that specific user's profile memories.
        This is the hard authorization filter — it runs before any
        similarity ranking, never mixed into one fuzzy score with it.
        """
        stmt = select(MemoryRecord).where(
            MemoryRecord.tenant_id == tenant_id, MemoryRecord.status == MemoryStatus.ACTIVE
        )
        if memory_type is not None:
            stmt = stmt.where(MemoryRecord.memory_type == memory_type)
        if user_id is not None:
            stmt = stmt.where(
                or_(MemoryRecord.user_id == user_id, MemoryRecord.user_id.is_(None))
            )
        else:
            stmt = stmt.where(MemoryRecord.user_id.is_(None))
        stmt = stmt.order_by(MemoryRecord.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        memory_type: MemoryType,
        content: str,
        provenance: MemoryProvenance,
        confidence: float,
        source_episode_id: uuid.UUID | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            provenance=provenance,
            confidence=confidence,
            status=MemoryStatus.ACTIVE,
            source_episode_id=source_episode_id,
            embedding=embedding,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def supersede(self, *, old: MemoryRecord, new: MemoryRecord) -> None:
        old.status = MemoryStatus.SUPERSEDED
        old.superseded_by = new.id
        await self._session.flush()

    async def soft_delete(self, *, record: MemoryRecord) -> None:
        record.status = MemoryStatus.DELETED
        await self._session.flush()
