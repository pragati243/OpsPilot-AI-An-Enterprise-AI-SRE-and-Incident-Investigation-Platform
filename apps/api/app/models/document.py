import uuid
from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentSourceType(StrEnum):
    RUNBOOK = "runbook"
    INCIDENT_REPORT = "incident_report"
    DOC = "doc"


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Retrievable knowledge (runbooks, incident reports, docs) for RAG.

    Hybrid search (vector + full-text) and the embedding column are added in
    the retrieval phase; this starts as the relational source of truth plus
    access_scope tags so ACL filtering is in place before retrieval lands.
    """

    __tablename__ = "documents"

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
