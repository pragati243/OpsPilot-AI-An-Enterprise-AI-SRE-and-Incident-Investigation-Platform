import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.document import EMBEDDING_DIMENSION


class MemoryType(StrEnum):
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PROFILE = "profile"


class MemoryProvenance(StrEnum):
    USER_CONFIRMED = "user_confirmed"
    SYSTEM_EXTRACTED = "system_extracted"
    IMPORTED = "imported"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Long-term memory distinct from LangGraph checkpoint state: knowledge
    reused across threads/sessions rather than within one conversation.

    Recall authorization is deliberately separate from similarity ranking:
    callers always filter by tenant_id/user_id/status in SQL first (see
    app/memory/recall.py), then rank what's left by `embedding` distance —
    a memory never becomes visible just because it's a close vector match.
    """

    __tablename__ = "memory_records"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null user_id means tenant-scoped (e.g. semantic facts about a service),
    # not belonging to any one engineer.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    memory_type: Mapped[MemoryType] = mapped_column(
        SAEnum(MemoryType, name="memory_type"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[MemoryProvenance] = mapped_column(
        SAEnum(MemoryProvenance, name="memory_provenance"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[MemoryStatus] = mapped_column(
        SAEnum(MemoryStatus, name="memory_status"), nullable=False, default=MemoryStatus.ACTIVE
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_records.id", ondelete="SET NULL"), nullable=True
    )
    source_episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION), nullable=True
    )
