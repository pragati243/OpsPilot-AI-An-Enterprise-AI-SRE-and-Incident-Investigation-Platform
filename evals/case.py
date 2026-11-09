"""Shared types between the dataset (evals/golden_cases.py) and the
evaluators (evals/evaluators.py) — kept in their own module so neither
side has to import the other to get at `GoldenCase`/`EvalOutcome`.

Flat module, not a package: every file in evals/ is a sibling script that
inserts apps/api onto `sys.path` itself, same idiom as apps/mcp-server's
files — see bootstrap.py there for why (a nested package layout fights
Python's sys.path resolution in a way a flat one just doesn't).
"""

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from fake_llm import RecordingFakeAgentLLM  # noqa: E402
from fixtures import EvalFixtures  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.agents.schemas import Assessment, InvestigationPlan, InvestigationReport  # noqa: E402
from app.models.incident import Incident  # noqa: E402
from app.models.remediation import RemediationProposal  # noqa: E402


@dataclass
class GoldenCase:
    id: str
    category: str
    description: str
    """What this case measures — shown in the report, not just a label."""

    service: str | None = None
    """None only when `incident_id_override` is set — those cases never
    reach a per-case incident of their own."""

    incident_id_override: uuid.UUID | None = None
    """Investigate this exact id instead of creating a fresh incident —
    either another tenant's real incident, or one that doesn't exist at
    all. Both are expected to fail identically (see
    evaluators.py::check_unauthorized_rejected_before_any_model_call)."""

    expect_incomplete: bool = False
    """True when `run_investigation` is expected to raise
    `InvestigationIncomplete` (today: only the `incident_id_override`
    cases)."""

    as_admin: bool = False

    inject_prompt_marker_into_title: bool = False
    """True only for the prompt_injection category: the runner appends
    `fixtures.PROMPT_INJECTION_MARKER` to this case's incident title
    instead of using the title plain — see golden_cases.py's
    `_prompt_injection_cases` for why the title (not a log line) is the
    honest place to stand in for attacker-influenceable text."""

    tool_call_script: list[list[dict]] = field(default_factory=list)
    plan_response: InvestigationPlan | None = None
    assessment_responses: list[Assessment] = field(default_factory=list)
    report_response: InvestigationReport | None = None

    evaluators: list["Evaluator"] = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class EvalOutcome:
    """Everything an evaluator might need, gathered once after running one
    case's investigation — evaluators only ever read from this, so adding a
    new check never needs a new DB round trip.
    """

    case: GoldenCase
    fixtures: EvalFixtures
    db: AsyncSession
    llm: RecordingFakeAgentLLM
    incident: Incident | None
    report: InvestigationReport | None
    incomplete_reason: str | None
    episode_evidence_items: list[dict]
    remediation_proposals: list[RemediationProposal]


Evaluator = Callable[[EvalOutcome], list[CheckResult]]
