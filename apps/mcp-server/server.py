"""OpsPilot MCP server: exposes the same 5 read-only diagnostic/knowledge
tools the LangGraph agent uses (apps/api/app/tools/) to any MCP client —
an IDE assistant, a chat client, another agent — over Streamable HTTP.

Auth piggybacks on the existing JWT stack: a client sends the same
`Authorization: Bearer <access_token>` it would send to the REST API (see
auth.py). There is deliberately no separate MCP-specific login or API key.

Run directly (`python server.py`, or `make mcp-dev`) for local dev. Port
8020: 8000/8010 and 5173/5180 are already taken by other projects/apps on
this dev machine (see apps/api/app/core/config.py's cors_allow_origins
comment for the same reasoning).
"""

import bootstrap  # noqa: F401  — must run before any `app.*` import below
import diagnostics_tools
import knowledge_tools
import uvicorn
from mcp.server.mcpserver import MCPServer

PORT = 8020

server = MCPServer(
    name="opspilot-mcp",
    version="0.1.0",
    instructions=(
        "Read-only SRE diagnostics and knowledge tools for OpsPilot AI. "
        "Every tool call is scoped to the caller's tenant via their bearer "
        "token; there is no cross-tenant visibility."
    ),
)

diagnostics_tools.register(server)
knowledge_tools.register(server)

app = server.streamable_http_app(stateless_http=True)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
