from app.guardrails.access_scope import allowed_scopes_for
from app.guardrails.tool_policy import enforce_tool_policy
from app.models.document import DocumentSourceType
from app.retrieval.hybrid_search import hybrid_search_documents
from app.tools.context import ToolContext
from app.tools.schemas import RunbookMatch, SearchRunbooksInput, SearchRunbooksResult


def _snippet(content: str, query: str, *, radius: int = 80) -> str:
    """Best-effort excerpt around a literal match. A purely semantic hit
    (no literal keyword overlap) falls back to the start of the content —
    there's no literal span to center on, and that's expected, not a bug.
    """
    lowered = content.lower()
    idx = lowered.find(query.lower())
    if idx == -1:
        return content[: radius * 2].strip()
    start = max(0, idx - radius)
    end = min(len(content), idx + len(query) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end].strip()}{suffix}"


@enforce_tool_policy("search_runbooks")
async def search_runbooks(
    ctx: ToolContext, params: SearchRunbooksInput
) -> SearchRunbooksResult:
    matches = await hybrid_search_documents(
        ctx.db,
        tenant_id=ctx.tenant_id,
        source_type=DocumentSourceType.RUNBOOK,
        query=params.query,
        allowed_scopes=allowed_scopes_for(ctx.user),
        limit=params.limit,
    )

    return SearchRunbooksResult(
        query=params.query,
        matches=[
            RunbookMatch(
                document_id=match.id,
                title=match.title,
                snippet=_snippet(match.content, params.query),
                score=match.score,
            )
            for match in matches
        ],
    )
