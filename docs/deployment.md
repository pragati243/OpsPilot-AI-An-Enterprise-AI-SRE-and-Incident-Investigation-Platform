# Deployment

Public HTTPS deployment: Render for the three app services (API, MCP
server, dashboard) + Redis, [Neon](https://neon.tech) for Postgres. Two
providers, not one, because Render's free Postgres **expires 30 days
after creation** (14-day grace period, then deleted) — wrong for a demo
meant to stay up. Neon's free tier has no such expiry and supports
pgvector on every plan, no add-on required.

Both are free-tier; the known cost of that is covered in
[Limitations](#limitations) below, not hidden.

## 1. Create the Neon project (Postgres)

1. Sign up at [neon.tech](https://neon.tech) (GitHub login is fine).
2. Create a project — any region close to Render's `oregon` region keeps
   latency down, but it isn't required to be in the same region.
3. In the Neon console's SQL editor, run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
4. Copy the pooled connection string from the Neon dashboard (the one
   Neon labels for use with serverless/pooled connections). It looks like:
   ```
   postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
   ```
   This needs one edit before it's usable here: the driver prefix must be
   `postgresql+asyncpg://`, not `postgresql://`, to match this project's
   async SQLAlchemy engine:
   ```
   postgresql+asyncpg://<user>:<password>@<host>/<dbname>?ssl=require
   ```
   (asyncpg's query-param spelling is `ssl=require`, not `sslmode=require`.)

Keep this connection string somewhere private — it's the `DATABASE_URL`
secret both Render services need in step 3.

## 2. Create the Render Blueprint

1. Sign up at [render.com](https://render.com) and connect your GitHub
   account.
2. New → Blueprint → select this repository. Render reads
   [`render.yaml`](../render.yaml) from the repo root and proposes four
   services: `opspilot-api`, `opspilot-mcp`, `opspilot-redis`,
   `opspilot-web`.
3. Approve the Blueprint. Render creates all four, but the two web
   services won't start successfully yet — they're still missing the
   secrets marked `sync: false` in `render.yaml`.

## 3. Fill in secrets

In the Render dashboard, under the `opspilot-shared-secrets` environment
group (shared by `opspilot-api` and `opspilot-mcp` — they must match, so
set this once, not per-service):

- `JWT_SECRET_KEY` — any random 32+ byte string (e.g. `openssl rand -hex 32`)
- `APP_SECRET_KEY` — same, a different random value

On `opspilot-api` specifically:

- `DATABASE_URL` — the Neon connection string from step 1
- `GROQ_API_KEY` *(optional)* — without it, the investigate endpoints
  return a clean 503 instead of a report; the rest of the app works fine
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` *(optional)* — without
  them, tracing is silently a no-op (see `app/observability/client.py`)

On `opspilot-mcp`:

- `DATABASE_URL` — the **same** Neon connection string

`REDIS_URL` is already wired automatically via `fromService` in
`render.yaml` — nothing to fill in there.

## 4. First deploy

Once the secrets are set, trigger a manual deploy for `opspilot-api` and
`opspilot-mcp` (or push a commit — see [CI gating](#ci-gating) below for
why that's usually the right trigger). `apps/api/docker-entrypoint.sh`
runs `alembic upgrade head` on every container start, so the schema is
created automatically on first boot — no separate migration step needed.

Seed the demo tenant once, from anywhere that can reach the Neon
connection string (your own machine is fine — this only needs network
access to Postgres, not to Render):

```bash
DATABASE_URL="<the Neon connection string>" uv run python infra/scripts/seed_demo_data.py
```

This creates the `demo-corp` tenant (`admin@demo-corp.io` /
`demo-password-change-me`) with services, runbooks, and incidents — the
same fixture `make seed-demo` creates locally. Safe to re-run; it's
idempotent.

## 5. Verify

```bash
curl https://opspilot-api.onrender.com/api/v1/healthz
# {"status":"ok"}

curl -X POST https://opspilot-api.onrender.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo-corp.io","password":"demo-password-change-me"}'
# {"access_token": "...", ...}
```

Then open `https://opspilot-web.onrender.com` in a browser and log in
with the same credentials.

## CI gating

Every service's `autoDeployTrigger` is `checksPass`, not `commit` — Render
waits for GitHub to report the `.github/workflows/ci.yml` check as passing
(lint, typecheck, the full pytest suite, and the Phase 10 golden
evaluation suite) before deploying a given commit. A push to `main` that
fails CI never reaches production; it isn't a separate webhook or deploy
step, it's this one Blueprint setting.

## Limitations

Stated plainly rather than discovered later:

- **Render free web services spin down after 15 minutes idle** and take
  about a minute to wake back up. The first request after a quiet period
  will be slow; this is Render's free-tier behavior, not an application
  bug.
- **Neon's free compute auto-suspends after 5 minutes idle** too, with a
  similar cold-start cost on the next query. Independent of Render's
  spin-down — both can stack on a truly cold demo.
- **`GROQ_API_KEY` is not set by default.** The investigate endpoints
  return a clean 503 ("Investigation service is not configured") rather
  than a report until a real key is added — this is the same fallback
  verified throughout local development (see the Phase 3/7 notes in the
  main [README](../README.md)), not something broken by deployment.
- **Render's free Key Value (Redis) is in-memory only, 25MB, one per
  workspace.** Fine for rate-limit counters, which don't need to survive
  a restart — not a general-purpose cache.
