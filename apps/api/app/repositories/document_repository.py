import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentSourceType


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        tenant_id: uuid.UUID,
        query: str,
        source_type: DocumentSourceType,
        allowed_scopes: set[str],
    ) -> list[Document]:
        """Keyword match over title/content, ACL-filtered. Returns every
        visible match unranked and unlimited — callers rank and truncate,
        since cutting to a limit before ranking would silently drop better
        matches. Real hybrid (vector + keyword) search with reranking lands
        in the retrieval phase; this is the relational baseline with ACL
        filtering already in place.

        ACL rule: a document with an empty access_scope is visible to
        everyone in the tenant; otherwise the caller needs at least one
        matching scope. This is evaluated in Python, not SQL, since
        `allowed_scopes` is small and PostgreSQL array-overlap SQL adds
        complexity with no real benefit at this size.
        """
        pattern = f"%{query}%"
        stmt = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.source_type == source_type,
            or_(Document.title.ilike(pattern), Document.content.ilike(pattern)),
        )
        result = await self._session.execute(stmt)
        documents = list(result.scalars().all())

        return [
            doc
            for doc in documents
            if not doc.access_scope or set(doc.access_scope) & allowed_scopes
        ]

    async def get_by_id(
        self, *, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> Document | None:
        """Tenant-scoped only — same pattern as every other repository's
        get_by_id. ACL (access_scope) is a finer-grained check the caller
        makes itself, same as `search` leaves it to the caller's
        `allowed_scopes`, so there's one place that owns "what scopes can
        this user see" (app/guardrails/access_scope.py) rather than two.
        """
        result = await self._session.execute(
            select(Document).where(
                Document.tenant_id == tenant_id, Document.id == document_id
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        title: str,
        source_type: DocumentSourceType,
        content: str,
        access_scope: list[str],
        created_by: uuid.UUID | None,
    ) -> Document:
        document = Document(
            tenant_id=tenant_id,
            title=title,
            source_type=source_type,
            content=content,
            access_scope=access_scope,
            created_by=created_by,
        )
        self._session.add(document)
        await self._session.flush()
        return document
