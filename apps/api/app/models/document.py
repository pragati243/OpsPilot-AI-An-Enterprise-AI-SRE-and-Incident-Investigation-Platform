import uuid
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# BAAI/bge-small-en-v1.5 via fastembed — see app/retrieval/embeddings.py.
EMBEDDING_DIMENSION = 384


class DocumentSourceType(StrEnum):
    RUNBOOK = "runbook"
    INCIDENT_REPORT = "incident_report"
    DOC = "doc"


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Retrievable knowledge (runbooks, incident reports, docs) for RAG.

    `embedding` and `search_vector` back the two legs of hybrid search in
    app/retrieval/hybrid_search.py (dense + full-text), fused with RRF.
    `embedding` is nullable because older rows (or documents written before
    ingestion computes an embedding) simply drop out of the vector leg —
    full-text search still finds them.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_search_vector", "search_vector", postgresql_using="gin"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[DocumentSourceType] = mapped_column(
        SAEnum(DocumentSourceType, name="document_source_type"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    access_scope: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, default=list
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION), nullable=True
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', title || ' ' || content)", persisted=True),
        nullable=False,
    )
