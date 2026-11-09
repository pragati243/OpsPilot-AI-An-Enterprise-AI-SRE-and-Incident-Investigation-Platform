#!/bin/sh
# Migrate-then-serve: runs on every container start, not just the first.
# `alembic upgrade head` is a no-op once already at head, so this is safe
# to repeat on every restart/redeploy rather than needing a separate
# one-off "pre-deploy" step (which Render's free tier doesn't offer).
set -eu

cd /app/apps/api
uv run --project /app --frozen --no-dev alembic upgrade head
cd /app

exec uv run --frozen --no-dev uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port "${PORT:-8010}"
