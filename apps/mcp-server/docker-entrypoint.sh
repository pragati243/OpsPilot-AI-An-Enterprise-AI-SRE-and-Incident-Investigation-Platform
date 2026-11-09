#!/bin/sh
# No migration step here — the MCP server never owns schema, it only
# reads/writes through apps/api's existing models via bootstrap.py's
# sys.path insert. Whichever deploys apps/api first already migrated.
set -eu

exec uv run --frozen --no-dev uvicorn server:app --app-dir apps/mcp-server --host 0.0.0.0 --port "${PORT:-8020}"
