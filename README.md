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
| 5 | Memory system | ✅ Done |
| 6 | Langfuse observability | ✅ Done |
| 7 | API completion (SSE, rate limiting) | ✅ Done |
| 8 | React + TypeScript dashboard | ✅ Done |
| 9 | MCP server | ✅ Done |
| 10 | Evaluation suite + CI quality gate | ⏳ Next |
| 11 | Docker / CI/CD / deployment | Not started |

## Repository layout

```
apps/api/        FastAPI backend: core, db, models, schemas, repositories,
                  api/v1, tools (+ simulator), guardrails, agents, retrieval,
                  memory, observability
apps/mcp-server/ MCP server exposing diagnostic tools as resources
apps/web/        React + TypeScript dashboard (Vite)
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
make dev                      # run the API with autoreload on :8010
make seed-demo                # seed one demo tenant with services/runbooks/incidents
```

Then the dashboard, in a second terminal:

```bash
cd apps/web
cp .env.example .env          # points at the API; default matches make dev's :8010
npm install
npm run dev                   # http://localhost:5180
```

And, optionally, the MCP server for tool-using clients (an IDE assistant, another
agent) — it needs the same API running for its DB/auth, nothing extra of its own:

```bash
make mcp-dev                  # Streamable HTTP on :8020
```

Run the test suite (spins up an ephemeral, tmpfs-backed test Postgres):

```bash
make test
```

> **Note for this dev machine specifically:** `docker-compose.yml` maps
> Postgres/Redis to non-default host ports (5544/5545/6399), the API runs
> on :8010 not :8000, and the dashboard runs on :5180 not Vite's default
> :5173 — this machine already runs a native Postgres service on 5432, a
> native Memurai (Redis-compatible) service on 6379, a WSL relay on 5433,
> and two unrelated projects' dev servers on 8000 and 5173. If you're on a
> clean machine without those, feel free to remap everything back to the
> standard ports (and update `cors_allow_origins` in
> `apps/api/app/core/config.py` to match if you change the frontend's).

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

### Memory system

`apps/api/app/memory/` is long-term memory distinct from the LangGraph
checkpointer (conversation/workflow state within one run) — knowledge
reused across separate investigations. Four pieces:

- **Policy** (`policy.py`) — a deterministic gate every memory write passes
  through regardless of what the extraction LLM was told: content-length
  bounds, regex backstops against secret/credential-shaped text and
  prompt-injection-shaped text, and profile-ownership checks. This runs
  whether a successful prompt injection got past the extraction prompt or
  not — it's a second, independent line of defense.
- **Extraction** (`extraction.py`) — after a report is finalized (never
  before — nothing gets written to memory from unverified tool output), an
  LLM call proposes a few general, reusable facts (architecture facts,
  confirmed fixes). Semantic/procedural memory only; profile memory is
  explicitly set by the user (`PUT /api/v1/memories/profile`) since there's
  no chat signal yet to infer it from.
- **Supersession** (`write.py`) — a new fact whose embedding is a
  near-duplicate (cosine similarity ≥ 0.92) of an existing active memory in
  the same scope replaces it rather than creating a duplicate; the old
  record is marked `superseded` with a pointer to the new one, never
  deleted outright.
- **Recall** (`recall.py`) — tenant/user/status filtering (authorization)
  always happens first in SQL; only records that already passed it get
  ranked by embedding similarity. A memory can never surface just because
  it's a close vector match to an unauthorized caller.

This closes the loop on the spec's worked example end to end, covered by
`test_monday_friday_scenario_recalls_and_supersedes_memory` and
`test_plan_prompt_includes_recalled_memory_with_verify_instruction` in
`apps/api/tests/test_agent_graph.py`: a Monday incident gets investigated
and a fact about the service is extracted into memory; a Friday incident
on the same service recalls that fact into the **plan** node's prompt,
explicitly framed as something to verify against current evidence, never
assume; resolving it the same way supersedes the memory rather than
duplicating it. Separately, a user's stated report-style preference
(`PUT /api/v1/memories/profile`) is recalled into the **report** node,
giving the "engineer prefers concise reports with evidence first" example
from the spec a real, working path. Users can inspect
(`GET /api/v1/memories`), correct (`PATCH .../{id}`), and delete
(`DELETE .../{id}`) their own memories.

### Observability (Langfuse)

`apps/api/app/observability/` wires the whole agent run into Langfuse
(v5, OTel-based SDK — the API changed significantly from older tutorials,
so this was built directly against the installed SDK, not copied from
docs). One root span per investigation (`investigate_incident`, created in
`graph.py::run_investigation`), with `propagate_attributes` carrying
`user_id`/`session_id`/`tenant_id`/workflow version to every child
observation. Underneath it: a `node:*` span per LangGraph node, a
`generation` span per LLM call (model name + token usage, via a tiny
`include_raw=True` trick to pull `usage_metadata` back out of
`with_structured_output`), a `tool:*` span for *every* tool call — added
once in `enforce_tool_policy` so all 7 tools get it for free regardless of
whether the LLM invoked it or app code did — and a `retriever` span for
hybrid search carrying ranked document ids/titles/scores, never raw
content.

Verified against a real Langfuse Cloud project (not just unit tests): ran
a full investigation and pulled the trace back via the API —
`investigate_incident → node:intake → node:plan → (node:agent ↔
node:execute_tools, with tool:get_service_health, tool:search_runbooks,
and a nested hybrid_search_documents retriever span) → node:assess →
node:report → tool:create_incident_report, tool:propose_remediation` — 15
observations, correctly typed and nested, with `user_id`/`session_id`
confirmed propagated onto the root span.

Redaction is defense in depth, not a single check: `app/core/redaction.py`
holds the shared secret-pattern regexes (reused by the memory policy
gate), `app/observability/masking.py` is the global `mask` callback
Langfuse runs on every captured field (redacts secrets, blanks
sensitive-looking keys like `Authorization` outright, truncates long
strings), and `app/observability/serialization.py` additionally bounds
message previews to 500 chars *before* that global pass even runs — so a
massive tool output is never fully captured in the first place, not just
redacted after the fact. Tests never hit the real Langfuse API: `.env`'s
real keys are explicitly blanked in `tests/conftest.py` (environment
variables, not `os.environ.pop`, since pydantic-settings reads `.env`
directly and would otherwise win), and the suite instead asserts that
every span call is a silent no-op without them.

### API completion

- **Rate limiting** (`app/core/rate_limit.py`) — a Redis fixed-window
  counter (`INCR`+`EXPIRE`), the first real use of Redis in this project
  beyond the readiness check. `/auth/login` and `/auth/register-tenant`
  are limited by client IP (no user identity exists yet); `/investigate`
  and `/investigate/stream` share one per-user budget, since they hit the
  same expensive LLM backend. A 429 carries a `Retry-After` header computed
  from the key's actual remaining TTL. Tests get their own Redis logical DB
  (`/15`, flushed before every test) — rate-limit counters live outside the
  per-test Postgres transaction rollback, so without this later tests would
  start failing from earlier tests' calls to the same endpoint, which is
  exactly what happened the first time this was wired up.
- **SSE streaming** (`stream_investigation` in `graph.py`, `POST
  /incidents/{id}/investigate/stream`) — the same graph, same bounds, same
  Langfuse trace, but surfaced via LangGraph's `astream(stream_mode=
  "updates")` as a `node_complete` event per node and one terminal `report`
  or `error` event, instead of blocking until the whole investigation
  finishes. Deliberately POST, not GET+EventSource — this needs a normal
  `Authorization` header, which `EventSource` can't send.
- **Tenant isolation, the audit-trail half** — `get_current_user` binds
  `tenant_id`/`user_id` into structlog's contextvars, so every log line for
  the rest of that request carries them automatically. (The enforcement
  half predates this phase: every repository call has always filtered by
  `tenant_id`, verified by a cross-tenant test in nearly every phase so
  far.)
- **Graceful fallback on LLM failure** — caught live, not just in a unit
  test: with no `GROQ_API_KEY` configured, `ChatOpenAI`'s constructor
  raises `openai.OpenAIError` *during FastAPI dependency resolution*,
  before a route's own `try/except` ever runs — so it was reaching the
  client as a bare 500 with an internal SDK traceback. Fixed by checking
  for the key explicitly in `build_groq_llm()` and turning that into a
  clean 503 inside the `get_agent_llm` dependency itself. Both investigate
  endpoints also catch any *other* unexpected failure (a mid-call Groq
  timeout, a network blip) the same way — never a raw 500, and the
  `RuntimeError`'s own message never reaches the response body.

### Dashboard

`apps/web/` is a Vite + React 19 + TypeScript SPA (Tailwind v4 for
styling, `react-router` for routing) — a thin, honest client over the API
built in Phases 1–7, nothing more:

- **Auth** (`lib/auth.tsx`) — login, token persistence in `localStorage`,
  a `/auth/me` check on load. No silent-refresh interceptor; a deliberate
  demo-scale simplification, not an oversight — an expired token just
  sends you back to `/login`.
- **Incidents** — list, create, and a detail page whose **Investigate**
  button drives the real SSE endpoint (`lib/api.ts::investigateStream`,
  fetch + a manual `ReadableStream` reader, since `EventSource` can't send
  the `Authorization` header the backend requires) into a live
  intake → plan → gather → assess → report stage indicator, ending in the
  rendered diagnosis/confidence/citations or — just as importantly — the
  backend's clean error message if the LLM isn't configured or fails.
- **Remediation approval** — the incident detail page lists proposals and,
  for admin/approver roles, surfaces Approve/Reject buttons wired to the
  endpoints added alongside this phase (`apps/api/app/api/v1/
  remediations.py` — there wasn't one before; a static "pending" list with
  nothing actionable would have been a dead end for the dashboard's
  "approval" surface the spec calls for).
- **Memory** — lists semantic/procedural/profile memories, lets a user
  correct or delete their own, and includes the form that actually
  exercises `PUT /memories/profile` — the one concrete path to the spec's
  "engineer prefers concise reports with evidence first" example.

**Verified by actually driving it**, not just a clean `tsc -b`: no
`chromium-cli` on this native Windows setup, so verification used a
one-off Playwright script (not a project dependency) to drive a real
headless Chromium against both dev servers — login → incidents list with
real seeded data → incident detail → Investigate (correctly rendering the
backend's 503 live, since no `GROQ_API_KEY` is configured) → remediation
panel → Memory page, setting and confirming a profile preference
end-to-end, including watching supersession fire on a second save. Only
console output was the *expected* 503 — nothing unexpected threw.

### MCP server

`apps/mcp-server/` exposes the same 5 read-only diagnostic/knowledge tools
(`get_service_health`, `query_logs`, `get_service_metrics`, `search_runbooks`,
`search_past_incidents`) to any MCP client over Streamable HTTP — an IDE
assistant, a chat client, another agent — rather than just the LangGraph
workflow built in Phase 3. It's a thin sibling app, not a second backend:
`bootstrap.py` puts `apps/api` on `sys.path` so every tool call runs the exact
same `apps/api/app/tools/` functions, `ToolContext`, and Postgres connection
the REST API and the agent already use — no duplicated logic, no second
schema to drift.

- **Auth** (`auth.py::authenticated_tool_context`) — an MCP client sends the
  same `Authorization: Bearer <access_token>` it would send the REST API
  (`Context.headers`, which the SDK's own docstring is explicit is
  client-supplied input, never trusted without `decode_token` verifying the
  signature). There's deliberately no second login flow or API-key system —
  one JWT, one set of tenant/role claims, for both surfaces.
- **Tools** (`diagnostics_tools.py`, `knowledge_tools.py`) — each one builds
  the same Pydantic input the HTTP layer builds, calls the existing tool
  function with an authenticated `ToolContext`, and returns a `dict[str,
  Any]` (the specific generic, not a bare `dict` — the SDK only derives a
  structured-output schema, and so only populates `structured_content`, for
  an annotation it can actually turn into a schema). A domain failure (unknown
  service, bad `time_window`) or an auth failure is re-raised as `mcp.ToolError`
  (`auth.py::call_tool_fn`) so the client sees the real message instead of a
  generic "Error executing tool" crash string.
- **Resource template** (`knowledge_tools.py::read_runbook`,
  `runbook://{document_id}`) — `search_runbooks` returns a `document_id` per
  match; a client fetches the full text on demand instead of every search
  result paying for full-content transfer upfront. An unknown id, a
  wrong-tenant id, and an ACL-denied id all raise the same
  `ResourceNotFoundError` — deliberately indistinguishable, same reasoning as
  `ServiceNotFoundError` elsewhere in the tool layer.

**Verified over the real protocol, not by calling the tool functions
directly**: `apps/mcp-server/tests/test_mcp_server.py` spins up the actual
`uvicorn` ASGI app (a bare in-process ASGI transport doesn't drive the
lifespan protocol the SDK's `StreamableHTTPSessionManager` needs to start, so
only a real running server exercises this honestly) and drives it with the
MCP SDK's own `ClientSession` over `streamable_http_client` — real
`initialize`, real `tools/list`, real `tools/call`, real `resources/read` —
against real seeded Postgres rows and a real signed JWT. It covers: the tool
roster, a missing-token call failing cleanly, a real authenticated call
returning real structured data, an unknown-service call failing with the
actual tool error message (not a crash), and the search → resource-read
round trip. 115/115 backend tests pass (109 from Phases 1–8 plus 6 new here),
`ruff` and `mypy` clean on `apps/mcp-server` too.

Further setup instructions will be filled in as each phase lands.
