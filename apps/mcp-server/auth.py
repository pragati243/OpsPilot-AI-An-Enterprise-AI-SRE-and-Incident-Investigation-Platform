import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import bootstrap  # noqa: F401  — must run before any `app.*` import below
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from pydantic import BaseModel

from app.core.security import InvalidTokenError, TokenType, decode_token
from app.db.session import AsyncSessionLocal
from app.repositories.user_repository import UserRepository
from app.tools.context import ToolContext
from app.tools.exceptions import ToolError as AppToolError


class McpAuthError(Exception):
    """Raised for a missing/invalid/expired bearer token, or an inactive
    user. MCP's own dispatcher turns an exception raised inside a tool
    into a protocol-level tool error — this doesn't need its own
    try/except at each call site, same as every other ToolError subclass
    in apps/api/app/tools/.
    """


@asynccontextmanager
async def authenticated_tool_context(ctx: Context) -> AsyncIterator[ToolContext]:
    """Every tool/resource handler in this server opens one of these. The
    MCP client authenticates exactly like an API client does — the same
    JWT issued by POST /api/v1/auth/login, as an `Authorization: Bearer`
    header on the Streamable HTTP request — so there is no second
    authentication system to keep in sync with the first. `ctx.headers`
    is client-supplied input, same caveat the SDK's own docstring gives:
    it's never trusted without `decode_token` verifying the signature.
    """
    headers = ctx.headers or {}
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise McpAuthError("Missing or malformed Authorization header")
    token = auth_header.split(" ", 1)[1].strip()

    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
        user_id = uuid.UUID(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise McpAuthError("Invalid or expired token") from exc

    async with AsyncSessionLocal() as db:
        user = await UserRepository(db).get_by_id(user_id)
        if user is None or not user.is_active:
            raise McpAuthError("User not found or inactive")
        yield ToolContext(tenant_id=user.tenant_id, user=user, db=db)


async def call_tool_fn(
    ctx: Context,
    fn: Callable[..., Awaitable[Any]],
    params: BaseModel,
) -> dict[str, Any]:
    """Runs one of apps/api's existing tool functions inside an
    authenticated ToolContext and returns a JSON-able dict.

    Translates both a bad/missing bearer token and a domain failure
    (unknown service, bad time_window, ...) into `mcp.ToolError` — the
    SDK's own "anticipated failure" type — so the client/model sees the
    actual message (e.g. "Service 'bogus' not found") instead of the
    generic "Error executing tool <name>" it substitutes for a crash.
    """
    try:
        async with authenticated_tool_context(ctx) as tool_ctx:
            result = await fn(tool_ctx, params)
    except (McpAuthError, AppToolError) as exc:
        raise McpToolError(str(exc)) from exc
    return result.model_dump(mode="json")
