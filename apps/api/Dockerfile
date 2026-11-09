# Build context is the repo root (pyproject.toml/uv.lock live there, not
# under apps/api) — see render.yaml / `docker build -f apps/api/Dockerfile .`
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/api ./apps/api

# --no-dev: pytest/ruff/mypy aren't needed to run the app; alembic is a
# main dependency (not dev), so migrations still work.
RUN uv sync --frozen --no-dev
RUN chmod +x apps/api/docker-entrypoint.sh

EXPOSE 8010

ENTRYPOINT ["/app/apps/api/docker-entrypoint.sh"]
