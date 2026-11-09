"""Exercises the MCP server over the real Streamable HTTP protocol — an
actual `ClientSession` talking to an actual running `uvicorn` instance —
rather than calling the registered tool functions directly in-process.
That distinction matters here specifically: it's the only way to prove
`ctx.headers` round-trips a real `Authorization` header end to end, which
every tool/resource call's auth depends on.

A real server is used (not an in-process ASGI transport) because the MCP
Starlette app only starts its `StreamableHTTPSessionManager` via the ASGI
lifespan protocol (`lifespan=lambda app: session_manager.run()` in the SDK);
a bare ASGI transport doesn't drive lifespan events, so only a real running
server reliably exercises this path.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest
import pytest_asyncio
import server as mcp_server_module
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent, TextResourceContents

PORT = 8021
BASE_URL = f"http://127.0.0.1:{PORT}/mcp"


def _text_of(content: object) -> str:
    """Every tool/resource result exercised in this file returns plain
    text — narrows the SDK's general `TextContent | ImageContent | ...`
    union so assertions can read `.text` without mypy complaining about
    the other members, which this server never actually produces.
    """
    assert isinstance(content, TextContent | TextResourceContents)
    return content.text


@pytest_asyncio.fixture(scope="module")
async def mcp_live_server() -> AsyncIterator[str]:
    config = uvicorn.Config(
        mcp_server_module.app, host="127.0.0.1", port=PORT, log_level="warning"
    )
    uvicorn_server = uvicorn.Server(config)
    task = asyncio.create_task(uvicorn_server.serve())
    try:
        for _ in range(100):
            if uvicorn_server.started:
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("MCP test server did not start in time")
        yield BASE_URL
    finally:
        uvicorn_server.should_exit = True
        await task


@asynccontextmanager
async def open_session(url: str, token: str | None) -> AsyncIterator[ClientSession]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx2.AsyncClient(headers=headers, timeout=30.0) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def test_list_tools_includes_all_five(mcp_live_server: str):
    async with open_session(mcp_live_server, token=None) as session:
        tools = (await session.list_tools()).tools
        names = {t.name for t in tools}
        assert names == {
            "get_service_health",
            "query_logs",
            "get_service_metrics",
            "search_runbooks",
            "search_past_incidents",
        }


async def test_tool_call_without_token_is_a_clean_error(mcp_live_server: str):
    async with open_session(mcp_live_server, token=None) as session:
        result = await session.call_tool("get_service_health", {"service": "checkout-service"})
        assert result.is_error
        assert "Authorization" in _text_of(result.content[0])


async def test_get_service_health_round_trips_real_auth_and_data(
    mcp_live_server: str, mcp_fixture_tenant: dict
):
    token = mcp_fixture_tenant["token"]
    async with open_session(mcp_live_server, token=token) as session:
        result = await session.call_tool("get_service_health", {"service": "checkout-service"})
        assert not result.is_error, result.content
        payload = result.structured_content
        assert payload["service"] == "checkout-service"
        assert payload["status"] == "healthy"


async def test_get_service_health_unknown_service_is_a_clean_tool_error(
    mcp_live_server: str, mcp_fixture_tenant: dict
):
    token = mcp_fixture_tenant["token"]
    async with open_session(mcp_live_server, token=token) as session:
        result = await session.call_tool("get_service_health", {"service": "does-not-exist"})
        assert result.is_error
        assert "does-not-exist" in _text_of(result.content[0])


async def test_search_runbooks_then_read_runbook_resource(
    mcp_live_server: str, mcp_fixture_tenant: dict
):
    token = mcp_fixture_tenant["token"]
    async with open_session(mcp_live_server, token=token) as session:
        search_result = await session.call_tool("search_runbooks", {"query": "connection pool"})
        assert not search_result.is_error, search_result.content
        matches = search_result.structured_content["matches"]
        assert matches, "expected the seeded runbook to match"
        document_id = matches[0]["document_id"]

        resource_result = await session.read_resource(f"runbook://{document_id}")
        [content] = resource_result.contents
        assert "connection pool" in _text_of(content)


async def test_read_runbook_resource_unknown_id_is_not_found(
    mcp_live_server: str, mcp_fixture_tenant: dict
):
    token = mcp_fixture_tenant["token"]
    async with open_session(mcp_live_server, token=token) as session:
        with pytest.raises(Exception) as exc_info:
            await session.read_resource("runbook://00000000-0000-0000-0000-000000000000")
        assert "not found" in str(exc_info.value).lower()
