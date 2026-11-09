# OpsPilot evaluation suite

32 golden cases across the 8 scenario categories from
[`docs/architecture.md`](../docs/architecture.md) section 8, scored by
deterministic evaluators — the CI quality gate for Phase 10.

## Run it

```bash
make evals
# or directly:
uv run python evals/run_evals.py [--json-out report.json]
```

Needs a reachable `DATABASE_URL` with migrations applied — any of dev
Postgres, the test Postgres, or CI's ephemeral one. Each run creates its
own disposable tenant (and a second tenant for cross-tenant checks),
seeds everything the dataset needs, runs all 32 cases, and deletes both
tenants again — safe to run repeatedly against the same database. Exit
code is `0` only if every check in every case passed.

## What this does — and doesn't — verify

Every case fully **scripts** the model's responses (plan, assessment,
report) via `RecordingFakeAgentLLM` instead of calling a real LLM. That's
deliberate, not a shortcut forced by missing credentials — though
`GROQ_API_KEY` also happens not to be configured in this environment, so
a live-LLM run is unverified either way.

The reason to script responses even with a real key available: this suite
checks whether the **pipeline** handles each scenario shape correctly —
schema/persistence round-tripping, tenant isolation, approval-gating,
bounded execution, faithful evidence surfacing — not whether a model's
*judgment* is good. A scripted "known incident" case proves the system
correctly persists and cites a confident diagnosis; it says nothing about
whether a real model would *reach* that diagnosis unaided. Grading actual
model judgment needs LLM-as-judge metrics calibrated against
human-reviewed transcripts, which `docs/architecture.md` explicitly scopes
as a later addition ("add LLM-as-judge metrics only where they add value
... quality thresholds are only ever claimed once an actual evaluation
run supports them"). Nothing here claims that yet.

What every check *does* verify is real and meaningful:

- **known_incident** — diagnosis/confidence/citations survive the full
  round trip from the model's structured output through
  `create_incident_report` into the persisted `Episode`/`Incident` rows.
- **missing_evidence** — a deliberately low-confidence, uncertain report
  is persisted as-is, never silently upgraded to a confident one.
- **historical_repeat** — the plan node's `recall_memories()` call
  actually surfaces a seeded procedural memory into its prompt, and
  `search_past_incidents` actually surfaces a seeded past episode,
  checked by inspecting what was *really* sent to the model and what the
  real tool call *really* returned — not just trusting the scripted
  report's claims about them.
- **conflicting_incidents** — `search_past_incidents` surfaces *every*
  matching past incident for a service, never silently collapsing
  disagreeing history to one.
- **unauthorized_request** — a cross-tenant or fabricated incident id is
  rejected by the `intake` node before any model call happens at all
  (checked by asserting the recording fake's call counts are zero).
- **prompt_injection** — an attacker-influenceable string (standing in for
  an untrusted log line — see `fixtures.py` for why the incident title is
  the honest place to put it, not an invented hook into the log
  simulator) reaches the model's prompt as literal text, and the
  mutating tools (`create_incident_report`, `propose_remediation`) are
  never exposed to the model's own tool-calling loop regardless —
  checked directly against `build_tools_for_context`, not inferred.
- **tool_timeout** — when every tool call errors and the model keeps
  asking for more, the graph still terminates within
  `max_tool_calls`/`max_gather_iterations` and produces a report, rather
  than looping. This is a bounded *execution budget*, not per-tool
  retries — there's no retry-with-backoff mechanism in this codebase, and
  the case description says so rather than implying one exists.
- **dangerous_remediation** — a high-risk recommended action (database
  failover, deployment rollback) always lands `PENDING_APPROVAL`; there
  is no auto-approved tier at any risk level, checked against the real
  `remediation_proposals` row, not the model's claim about it.

## Layout

Flat modules, not the `datasets/`/`evaluators/` subpackages sketched in
`docs/architecture.md`'s repo tree — same reasoning as
`apps/mcp-server`'s flat layout: a sibling app/tool outside `apps/api`
inserting `apps/api` onto `sys.path` fights Python's import resolution
the moment it's nested more than one level deep. One flat `evals/`
directory sidesteps that entirely.

- `fixtures.py` — seeds the disposable eval tenant(s).
- `fake_llm.py` — `RecordingFakeAgentLLM`, a scriptable `AgentLLM` that
  also records every prompt it was sent.
- `case.py` — `GoldenCase`/`EvalOutcome`/`CheckResult` shared types.
- `golden_cases.py` — the 32 cases.
- `evaluators.py` — the deterministic check functions.
- `run_evals.py` — orchestrator, CLI, report, exit code.

## Extending this later

- A `--llm real` mode that runs the same cases against the real Groq
  model (via `build_groq_llm()`, already wired for the production
  investigate endpoints) and grades only the scripted-response-independent
  checks (authorization, approval-gating, bounded execution, schema
  validity) is a natural next step once `GROQ_API_KEY` is available — not
  built here because it can't be verified in this environment, and an
  unverified code path isn't worth shipping over a verified smaller one.
- LLM-as-judge scoring for diagnosis quality, once there's a
  human-reviewed reference set to calibrate against.
