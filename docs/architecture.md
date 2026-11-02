# OpsPilot AI — Architecture & Build Spec

**OpsPilot AI** — An Enterprise AI SRE and Incident Investigation Platform.

This document is the living source of truth for the project. It is built strictly
phase-by-phase (see `README.md` for current status); each phase is completed and
verified before the next begins.

## 1. Problem

When a production service fails, engineers need to inspect logs, search
documentation, review old incidents, determine root cause, and decide what to do
next. That process is slow and inconsistent, especially for failures the engineer
has never seen before.

OpsPilot acts as an AI investigation assistant. It gathers evidence from
authorized tools, retrieves relevant runbooks, recalls verified historical
resolutions, and prepares an incident report with suggested next steps.

The initial version uses a realistic simulated production environment, so the
project works without access to a real company's infrastructure. It can later be
connected to GitHub, Slack, monitoring systems, or an issue tracker.

## 2. What the system demonstrates

- **Evidence-driven incident investigation** — the agent queries service health,
  logs, metrics, runbooks, and previous incidents rather than guessing root cause.
- **Persistent, controlled memory** — remembers verified incidents, resolution
  outcomes, team preferences, and historical context across separate conversations.
- **Stateful agent workflow** — LangGraph plans an investigation, selects tools,
  assesses evidence, retries failed steps, requests human approval, and resumes
  interrupted workflows.
- **Enterprise-grade safety** — authorization, input/output checks, read-only
  diagnostics, and deterministic approval policies for dangerous actions.
- **Observable and measurable AI** — Langfuse traces, tool-call latency, failures,
  token usage, evaluation results, and incident investigation quality.

## 3. Production architecture

```
React + TypeScript dashboard   → Incident console · evidence · approval · memory
FastAPI application            → Auth · tenant isolation · rate limits · SSE streaming
LangGraph orchestrator         → Plan → investigate → retrieve → assess → report
Memory service                 → Profile, semantic facts, episodic history, summaries
Knowledge retrieval            → Hybrid search, reranking, ACL filters, citations
MCP and tool layer             → Logs, metrics, health, incidents, runbooks
Safety and approval            → Policy engine, action allowlist, durable approval
Data and observability         → PostgreSQL + pgvector · Redis · object storage · Langfuse
```

The key architectural decision: **separate the LLM's reasoning and
recommendations from the application code that enforces permissions and executes
tools.** The model can suggest a diagnosis; it cannot grant itself permission to
perform an action.

## 4. Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | Python, FastAPI, Pydantic v2 | Typed APIs and validation |
| LLM | Groq API (OpenAI-compatible) | Fast inference; model name configurable |
| Agent orchestration | LangGraph | Conditional workflows, checkpointing, resumability |
| LLM observability | Langfuse (v4 SDK) | Tracing, prompt versions, experiments, evaluations |
| Database | PostgreSQL, SQLAlchemy 2.x, Alembic | Durable application state and migrations |
| Vector retrieval | pgvector + Postgres full-text search | Dense + keyword retrieval, no extra mandatory DB |
| Cache / rate limiting | Redis | Cache, throttling, temporary coordination |
| Async jobs | Celery (or durable worker) | Background ingestion and evaluation |
| Tool integration | MCP over Streamable HTTP | Reusable tools and system integrations |
| Frontend | React, TypeScript, Vite | Operational dashboard |
| Testing | pytest, DeepEval / custom evaluators | Regression tests and AI quality measurement |
| Deployment | Docker, GitHub Actions, cloud hosting | Reproducible build and public demo |

Scope discipline: build a complete, tested core (P0) before adding every advanced
technique. A working agent with evidence, durable memory, secure tool execution,
evaluations, and a deployed interface beats a system that claims many frameworks
but cannot reliably solve one incident.

## 5. Feature specification

### P0 — must work in the live demo
- Incident investigation from a dashboard.
- Groq-powered LangGraph workflow.
- Tool calls for health, logs, metrics, and historical incidents.
- RAG with source citations and evidence.
- Cross-session long-term memory.
- PostgreSQL persistence and Langfuse traces.
- Authentication, authorization, and tests.
- Public HTTPS deployment with seeded demo data.

### P1 — strong differentiators
- MCP server exposing diagnostic tools.
- Durable LangGraph checkpoints.
- Human approval with approve / edit / reject.
- Hybrid retrieval, reranking, access-controlled documents.
- Offline evaluation dataset and CI quality gate.
- Streaming responses, retry policies, timeouts, fallbacks.

### P2 — advanced extensions
- GitHub issue/PR integration.
- Slack incident notifications.
- Multi-tenant analytics and per-user cost attribution.
- A/B testing for prompts and models.
- Incident trend detection and scheduled evaluations.
- Optional specialist agents, only when evaluations justify the complexity.

## 6. Memory system

Memory is not "store the last 20 messages." Different kinds of memory need
different retrieval methods and explicit rules about what is safe to remember.

| Memory type | Example | Storage |
|---|---|---|
| Short-term | Current investigation, recent messages | LangGraph checkpoint |
| Semantic | "Checkout uses PostgreSQL in the payments environment" | Postgres facts + vector retrieval |
| Episodic | Previous incident: evidence, diagnosis, resolution, outcome | Incident/episode records |
| Procedural | Verified steps for diagnosing connection pool exhaustion | Versioned runbooks |
| User profile | "Engineer prefers concise reports with evidence first" | User-scoped profile records |
| Cache | Result of a repeated health check | Redis with TTL; not authoritative |

**Lifecycle:** conversation + verified investigation → candidate memory
extraction (facts, preferences, episode, confidence) → deterministic memory
policy (schema validation, ownership check, conflict detection, injection
rejection) → persistent store (Postgres records + embeddings where useful) →
scoped recall on a future investigation (relevant, current, authorized memories
only).

Worked example: an engineer investigates high API latency Monday and confirms
DB connection-pool exhaustion. The system saves an episode (evidence, diagnosis,
approved resolution, outcome). A similar incident occurs Friday; the system
retrieves the earlier episode, compares its evidence against *current* metrics,
and proposes a diagnosis — but must still verify current evidence rather than
assume the old cause applies.

**Memory safety rules:**
- Never treat a user message or retrieved document as a trusted
  memory-writing instruction.
- Never store secrets, API keys, credentials, or unrestricted raw logs in
  long-term memory.
- Store provenance, tenant/user scope, timestamps, confidence, and
  supersession information.
- Allow users to inspect, correct, and delete their memories.
- Keep memory retrieval authorization separate from semantic similarity.
- Measure memory recall accuracy, update correctness, and false-memory rate.

The distinction to be able to explain: a **LangGraph checkpointer** holds
conversation/workflow state; the **long-term memory store** holds knowledge
reused across threads.

## 7. Agent workflow

A controlled LangGraph workflow, not an unrestricted agent loop:

1. **Intake and authorization** — validate request, tenant, user, incident scope.
2. **Plan investigation** — generate bounded steps, choose diagnostic tools.
3. **Gather evidence** — health checks, metrics, logs, RAG, episodic memory.
4. **Assess findings** — compare hypotheses against evidence; identify gaps.
5. **Confidence and safety gate** — request more evidence, state uncertainty, or
   prepare a report.
6. **Report, approval, and learning** — cited diagnosis, recommended actions,
   approval if needed, verified outcome recorded.

The workflow is bounded: max tool calls, retry counts, execution deadlines,
token limits. Structured Pydantic models for the investigation plan and final
report. If evidence is insufficient, the agent states that rather than
manufacturing a root cause.

### Tool contracts

- `get_service_health(service, environment)`
- `query_logs(service, time_window, severity, limit)`
- `get_service_metrics(service, time_window)`
- `search_runbooks(query, service, access_scope)`
- `search_past_incidents(query, service, access_scope)`
- `create_incident_report(incident_id, report)`
- `propose_remediation(incident_id, action)`

Diagnostic tools operate against a seeded simulator initially. Any future
integration with real production infrastructure must be separately
authenticated and authorized. Remediation never silently executes merely
because the LLM requested it — it goes through the approval policy engine.

MCP exposes reusable diagnostic capabilities as tools and, where appropriate,
runbooks/service metadata as resources. No single unrestricted
"execute arbitrary command" tool.

## 8. Observability and evaluation

Not optional decoration — this is one of the strongest ways to demonstrate
production AI understanding.

Instrument the complete request:
- Request/trace identifiers, user/tenant scope, workflow version.
- Each LangGraph node and LLM generation.
- Tool name, duration, success/failure, validated input/output metadata.
- Retrieval query, authorized document identifiers, ranks, citations.
- Prompt version, model name, token counts, cost when available.
- Retries, timeout events, safety blocks, approval outcomes.
- Evaluation scores linked to the test case.

Secrets, authorization tokens, unrestricted raw logs, and sensitive prompts are
redacted before export to Langfuse.

### Golden evaluation dataset (30–50 seeded cases)

| Scenario | What it measures |
|---|---|
| Known incident | Correct diagnosis and evidence |
| Missing evidence | Honest uncertainty rather than guessing |
| Historical repeat | Appropriate memory recall |
| Conflicting incidents | Correct handling of conflicting evidence |
| Unauthorized request | No cross-tenant leakage |
| Prompt injection in a log | No instruction-following from untrusted data |
| Tool timeout | Bounded retries and clear failure |
| Dangerous remediation | Approval required; no unauthorized execution |

Start with deterministic checks (citations, authorization, schema validity,
tool policy). Add LLM-as-judge metrics only where they add value, calibrated
against human-reviewed examples. Quality thresholds are only ever claimed once
an actual evaluation run supports them.

## 9. Repository structure

```
opspilot-ai/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── api/v1/
│   │   │   ├── core/              # config, security, logging
│   │   │   ├── db/                # SQLAlchemy, sessions
│   │   │   ├── models/            # ORM models
│   │   │   ├── schemas/           # Pydantic contracts
│   │   │   ├── repositories/
│   │   │   ├── services/
│   │   │   ├── agents/
│   │   │   │   ├── graph.py
│   │   │   │   ├── state.py
│   │   │   │   ├── nodes/
│   │   │   │   └── prompts/
│   │   │   ├── memory/
│   │   │   ├── retrieval/
│   │   │   ├── tools/
│   │   │   ├── guardrails/
│   │   │   └── observability/
│   │   ├── alembic/
│   │   └── tests/
│   ├── mcp-server/
│   │   ├── server.py
│   │   └── tools/
│   └── web/
│       ├── src/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── features/
│       │   └── lib/
│       └── package.json
├── packages/
│   └── shared-schemas/
├── evals/
│   ├── datasets/
│   ├── evaluators/
│   ├── run_evals.py
│   └── README.md
├── infra/
│   ├── docker/
│   └── scripts/
├── docs/
│   ├── architecture.md
│   ├── threat-model.md
│   ├── evaluation-report.md
│   └── deployment.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── Makefile
├── pyproject.toml
├── README.md
└── .github/workflows/ci.yml
```

## 10. Build phases

Each phase is built, tested, and confirmed with the project owner before the
next one starts. Status is tracked in `README.md`.

0. Repo scaffold, git, this architecture doc.
1. FastAPI backend foundation: config/logging/security, SQLAlchemy 2.x +
   Alembic, Postgres+pgvector via Docker, core ORM models, JWT auth, health
   endpoint, tests.
2. Simulated production environment + typed tool layer (health/logs/metrics/
   runbooks/incidents) with guardrails (read-only enforcement, action
   allowlist).
3. LangGraph agent workflow wired to Groq: plan → gather → assess → report,
   bounded execution, structured Pydantic contracts.
4. RAG/retrieval: pgvector hybrid search, ACL filtering, citations.
5. Memory system: semantic/episodic/procedural/profile records, memory policy
   engine, scoped recall.
6. Langfuse observability across nodes/tools/retrieval, with redaction.
7. API completion: SSE streaming, rate limiting, tenant isolation middleware.
8. React + TypeScript dashboard.
9. MCP server exposing the tool layer.
10. Golden evaluation dataset (30–50 cases) + CI quality gate.
11. Docker/CI/CD + public HTTPS deployment with seeded demo data.
