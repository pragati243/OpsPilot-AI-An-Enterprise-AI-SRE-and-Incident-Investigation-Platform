from app.guardrails.access_scope import allowed_scopes_for
from app.guardrails.tool_policy import enforce_tool_policy
from app.models.document import Document, DocumentSourceType
from app.repositories.document_repository import DocumentRepository
from app.tools.context import ToolContext
from app.tools.schemas import RunbookMatch, SearchRunbooksInput, SearchRunbooksResult


def _snippet(content: str, query: str, *, radius: int = 80) -> str:
    lowered = content.lower()
    idx = lowered.find(query.lower())
    if idx == -1:
        return content[: radius * 2].strip()
    start = max(0, idx - radius)
    end = min(len(content), idx + len(query) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end].strip()}{suffix}"


def _score(document: Document, query: str) -> float:
    """Keyword occurrence count, title weighted higher than body. A stand-in
    for real relevance scoring until the retrieval phase's hybrid search.
    """
    lowered_query = query.lower()
    return float(
        3 * document.title.lower().count(lowered_query)
        + document.content.lower().count(lowered_query)
    )


@enforce_tool_policy("search_runbooks")
async def search_runbooks(
    ctx: ToolContext, params: SearchRunbooksInput
) -> SearchRunbooksResult:
    documents = await DocumentRepository(ctx.db).search(
        tenant_id=ctx.tenant_id,
        query=params.query,
        source_type=DocumentSourceType.RUNBOOK,
        allowed_scopes=allowed_scopes_for(ctx.user),
    )

    ranked = sorted(documents, key=lambda doc: _score(doc, params.query), reverse=True)
    matches = [
        RunbookMatch(
            document_id=doc.id,
            title=doc.title,
            snippet=_snippet(doc.content, params.query),
            score=_score(doc, params.query),
        )
        for doc in ranked[: params.limit]
    ]
    return SearchRunbooksResult(query=params.query, matches=matches)
