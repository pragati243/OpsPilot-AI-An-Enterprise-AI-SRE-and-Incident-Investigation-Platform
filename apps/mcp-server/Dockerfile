# Build context is the repo root, same reasoning as apps/api/Dockerfile.
# Both apps/api and apps/mcp-server are copied in, preserving them as
# siblings under apps/ — apps/mcp-server/bootstrap.py finds apps/api via
# a path relative to its own location, so that layout has to match local
# dev exactly.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/api ./apps/api
COPY apps/mcp-server ./apps/mcp-server

RUN uv sync --frozen --no-dev
RUN chmod +x apps/mcp-server/docker-entrypoint.sh

EXPOSE 8020

ENTRYPOINT ["/app/apps/mcp-server/docker-entrypoint.sh"]
