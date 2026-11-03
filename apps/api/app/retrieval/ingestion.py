import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentSourceType
from app.repositories.document_repository import DocumentRepository
from app.retrieval.embeddings import embed_passages


async def ingest_document(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    source_type: DocumentSourceType,
    content: str,
    access_scope: list[str],
    created_by: uuid.UUID | None,
) -> Document:
    """Create a Document with its embedding computed up front — the only
    supported way to add one, so nothing lands in the knowledge base
    without being findable by the vector leg of hybrid search.
    """
    (embedding,) = await embed_passages([content])
    document = await DocumentRepository(db).create(
        tenant_id=tenant_id,
        title=title,
        source_type=source_type,
        content=content,
        access_scope=access_scope,
        created_by=created_by,
    )
    document.embedding = embedding
    await db.flush()
    return document
