# OpsPilot AI

**An Enterprise AI SRE and Incident Investigation Platform.**

When a production service fails, engineers need to inspect logs, search
documentation, review old incidents, determine root cause, and decide what to
do next. OpsPilot is an AI investigation assistant that gathers evidence from
authorized tools, retrieves relevant runbooks, recalls verified historical
resolutions, and prepares an incident report with suggested next steps —
backed by a controlled LangGraph workflow, durable cross-session memory, RAG
with citations, and full Langfuse observability.

The full design — architecture, memory system, agent workflow, tool
contracts, evaluation plan — lives in [`docs/architecture.md`](docs/architecture.md).
This repository is built strictly phase-by-phase against that spec.

## Build status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold, git, architecture doc | ✅ Done |
| 1 | FastAPI backend foundation, DB, auth | ✅ Done |
| 2 | Simulated prod environment + tool layer | ✅ Done |
| 3 | LangGraph agent workflow (Groq) | ✅ Done |
| 4 | RAG / retrieval | ✅ Done |
| 5 | Memory system | ⏳ Next |
| 6 | Langfuse observability | Not started |
| 7 | API completion (SSE, rate limiting) | Not started |
| 8 | React + TypeScript dashboard | Not started |
| 9 | MCP server | Not started |
| 10 | Evaluation suite + CI quality gate | Not started |
| 11 | Docker / CI/CD / deployment | Not started |

## Repository layout

```
apps/api/        FastAPI backend: core, db, models, schemas, repositories,
                  api/v1, tools (+ simulator), guardrails, agents, retrieval
                  (memory lands in a later phase)
apps/mcp-server/ MCP server exposing diagnostic tools as resources
apps/web/        React + TypeScript dashboard
packages/        Shared schemas used across apps
evals/           Golden dataset, evaluators, eval runner
infra/           Docker and provisioning scripts
docs/            Architecture, threat model, evaluation report, deployment
```

## Local development

Prerequisites: Docker Desktop, Python 3.12+, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # fill in real secrets; defaults work for local dev
uv sync --all-groups          # install Python deps into .venv
make up                       # Postgres (+pgvector) and Redis via docker-compose
make migrate                  # apply Alembic migrations
make dev                      # run the API with autoreload on :8000
make seed-demo                # seed one demo tenant with services/runbooks/incidents
```

Run the test suite (spins up an ephemeral, tmpfs-backed test Postgres):

```bash
make test
```

> **Note for this dev machine specifically:** `docker-compose.yml` maps
> Postgres/Redis to non-default host ports (5544/5545/6399) because this
> machine already runs a native Postgres service on 5432, a native Memurai
> (Redis-compatible) service on 6379, and a WSL relay on 5433. If you're on a
> clean machine without those, feel free to remap to the standard ports.

Other useful targets: `make lint` (ruff), `make typecheck` (mypy), `make revision m="..."`
(new Alembic migration). See the [`Makefile`](Makefile) for the full list.

### Simulated environment and tools

`make seed-demo` creates a `demo-corp` tenant (login `admin@demo-corp.io` /
`demo-password-change-me`) with six services — some healthy, some actively
degraded/down against a deterministic scenario catalog
(`apps/api/app/tools/simulator/scenarios.py`) — plus runbooks and a past
resolved incident. The seven tool contracts from the spec
(`get_service_health`, `query_logs`, `get_service_metrics`,
`search_runbooks`, `search_past_incidents`, `create_incident_report`,
`propose_remediation`) are implemented in `apps/api/app/tools/` as plain,
directly-callable async functions over that data, fully tested independent
of any agent. Every call is policy-checked and audit-logged via
`apps/api/app/guardrails/tool_policy.py`; `propose_remediation` additionally
runs through an action allowlist and always lands as `pending_approval` —
it can never execute anything itself.

### Agent workflow

`apps/api/app/agents/` is a LangGraph state machine: **intake** (validates
the incident belongs to the caller's tenant before any model call) →
**plan** (bounded hypothesis + tool-call plan) → **agent/execute_tools**
(ReAct-style loop over the five read-only tools, hard-capped by
`max_tool_calls` and `max_gather_iterations`) → **assess** (confidence +
missing-evidence gate) → **report** (structured diagnosis, which the *app*
— not the model — then deterministically persists via
`create_incident_report` and, for any recommended action that passes the
allowlist, `propose_remediation`). The LLM never calls the two mutating
tools directly; it can only produce a structured report that app code acts
on. All four LLM calls per node (plan/gather/assess/report) go through a
narrow `AgentLLM` protocol (`apps/api/app/agents/llm_client.py`), so the
whole graph is tested deterministically with a scripted fake
(`apps/api/tests/fakes.py`) and never needs a real `GROQ_API_KEY` in CI.

Try it once the API is running and seeded:

```bash
curl -X POST http://localhost:8010/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo-corp.io","password":"demo-password-change-me"}'
# then, with the returned access_token:
curl -X POST http://localhost:8010/api/v1/incidents/<incident_id>/investigate \
  -H "Authorization: Bearer <token>"
```

This requires a real `GROQ_API_KEY` in `.env` (Groq's OpenAI-compatible
endpoint, configured in `app/agents/llm_client.py::build_groq_llm`) — the
test suite doesn't need one, but hitting the live endpoint does.

### Retrieval (RAG)

`search_runbooks` now does real hybrid search instead of Phase 2's
ILIKE-only match: dense retrieval (`pgvector` cosine distance over
384-dim embeddings from `BAAI/bge-small-en-v1.5` via `fastembed` — ONNX,
CPU, no `torch`, no API key) fused with Postgres full-text search
(`tsvector` + GIN index over title+content) using Reciprocal Rank Fusion.
ACL filtering (`access_scope`) is pushed into both legs of the SQL itself
(`apps/api/app/retrieval/hybrid_search.py`), not applied in Python after
the fact. A cosine-distance cutoff drops candidates that are "the best of
a bad lot" rather than an actual match — verified with real distances: an
on-topic query lands around 0.28-0.33, an off-topic one around 0.60.

Documents only ever enter the system through
`apps/api/app/retrieval/ingestion.py::ingest_document`, which computes the
embedding at write time — there's no path that creates a Document without
one. See `apps/api/tests/test_tools_knowledge.py` for the test that proves
the point: a query sharing zero literal words with a runbook still finds it
(and a genuinely unrelated query correctly finds nothing).

Further setup instructions will be filled in as each phase lands.
