import uuid
from typing import Annotated, Any

import bootstrap  # noqa: F401  — must run before any `app.*` import below
from auth import McpAuthError, authenticated_tool_context, call_tool_fn
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError
from pydantic import Field

from app.guardrails.access_scope import allowed_scopes_for
from app.models.document import DocumentSourceType
from app.repositories.document_repository import DocumentRepository
from app.tools.incidents import search_past_incidents as _search_past_incidents
from app.tools.runbooks import search_runbooks as _search_runbooks
from app.tools.schemas import SearchPastIncidentsInput, SearchRunbooksInput


def register(server: MCPServer) -> None:
    """Registers the 2 read-only knowledge tools plus the `runbook://`
    resource template. `search_runbooks` returns a `document_id` per match;
    a client follows up with `runbook://{document_id}` to fetch the full
    text on demand, rather than every search result paying for full-content
    transfer upfront.
    """

    @server.tool(
        description="Search runbooks for diagnostic guidance relevant to a free-text query."
    )
    async def search_runbooks(
        query: str,
        service: str | None = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        return await call_tool_fn(
            ctx,
            _search_runbooks,
            SearchRunbooksInput(query=query, service=service, limit=limit),
        )

    @server.tool(
        description=(
            "Search previously recorded incidents for similar evidence, diagnoses, "
            "and resolutions."
        )
    )
    async def search_past_incidents(
        query: str,
        service: str | None = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        return await call_tool_fn(
            ctx,
            _search_past_incidents,
            SearchPastIncidentsInput(query=query, service=service, limit=limit),
        )

    @server.resource(
        "runbook://{document_id}",
        description=(
            "Full text of one runbook, referenced by the document_id a "
            "search_runbooks match returned."
        ),
        mime_type="text/plain",
    )
    async def read_runbook(document_id: str, *, ctx: Context) -> str:
        try:
            async with authenticated_tool_context(ctx) as tool_ctx:
                try:
                    doc_id = uuid.UUID(document_id)
                except ValueError:
                    raise ResourceNotFoundError(f"Runbook {document_id!r} not found") from None

                doc = await DocumentRepository(tool_ctx.db).get_by_id(
                    tenant_id=tool_ctx.tenant_id, document_id=doc_id
                )
                visible = (
                    doc is not None
                    and doc.source_type == DocumentSourceType.RUNBOOK
                    and (
                        not doc.access_scope
                        or set(doc.access_scope) & allowed_scopes_for(tool_ctx.user)
                    )
                )
                if not visible:
                    # Same shape whether the id is unknown or belongs to
                    # another tenant/ACL scope — never reveals which.
                    raise ResourceNotFoundError(f"Runbook {document_id} not found")
                assert doc is not None
                return doc.content
        except McpAuthError as exc:
            raise ResourceError(str(exc)) from exc
