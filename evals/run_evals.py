"""Runs the golden evaluation dataset against the real LangGraph workflow
and a real (disposable) Postgres tenant, scoring every case with the
deterministic evaluators in evaluators.py. This is the "CI quality gate"
half of Phase 10 — see evals/README.md for what it does and does not
claim to verify.

Usage:
    uv run python evals/run_evals.py [--json-out PATH]

Exit code is 0 only if every check in every case passed. Points
`DATABASE_URL` wherever the environment already has it pointed (dev
Postgres locally, the CI Postgres service in GitHub Actions) — same
convention as infra/scripts/seed_demo_data.py, not a special eval-only
database.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

# Forces app.core.logging's JSON renderer instead of structlog's default
# dev ConsoleRenderer, which emits Unicode decoration that crashes with
# UnicodeEncodeError on a Windows console using a non-UTF-8 codepage the
# moment any tool call logs — not an eval/pipeline bug, a terminal-encoding
# one. Same fix, same reasoning as apps/api/tests/conftest.py's ENV=test.
os.environ.setdefault("ENV", "test")

from case import CheckResult, EvalOutcome, GoldenCase  # noqa: E402
from fake_llm import RecordingFakeAgentLLM  # noqa: E402
from fixtures import (  # noqa: E402
    PROMPT_INJECTION_MARKER,
    EvalFixtures,
    build_fixtures,
    new_investigation_incident,
    teardown_fixtures,
    tool_context_for,
)
from golden_cases import build_golden_cases  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.agents.graph import InvestigationIncomplete, run_investigation  # noqa: E402
from app.agents.schemas import Assessment, InvestigationPlan, InvestigationReport  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.memory.schemas import ExtractedMemories  # noqa: E402
from app.repositories.episode_repository import EpisodeRepository  # noqa: E402
from app.repositories.incident_repository import IncidentRepository  # noqa: E402
from app.repositories.remediation_repository import RemediationRepository  # noqa: E402

# app.main (which normally does this at import time) is never imported
# here — this is the explicit equivalent, so tool-call/node logging during
# the run is JSON (ASCII-safe, and more useful piped into CI logs anyway)
# instead of structlog's un-configured lazy default, which is also a
# Unicode-decorated console renderer.
configure_logging()


async def _run_one_case(
    db: AsyncSession, fixtures: EvalFixtures, case: GoldenCase
) -> list[CheckResult]:
    ctx = tool_context_for(fixtures, db, as_admin=case.as_admin)

    if case.incident_id_override is not None:
        incident_id = case.incident_id_override
    else:
        assert case.service is not None, f"{case.id} needs service or incident_id_override"
        title = f"[eval] {case.id}"
        if case.inject_prompt_marker_into_title:
            title = f"{title} — {PROMPT_INJECTION_MARKER}"
        incident = await new_investigation_incident(db, fixtures, service=case.service, title=title)
        incident_id = incident.id

    # Every case that reaches the report node also triggers a learn-node
    # call for ExtractedMemories (app/agents/nodes/report.py), which no
    # case scripts a response for — not what any of these cases are
    # testing. Without this, report.py's own try/except around that call
    # swallows the resulting AssertionError and logs it as a warning, which
    # is harmless but drowns the real output in identical noise.
    structured_responses: dict[type, list] = {ExtractedMemories: [ExtractedMemories()]}
    if case.plan_response is not None:
        structured_responses[InvestigationPlan] = [case.plan_response]
    if case.assessment_responses:
        structured_responses[Assessment] = list(case.assessment_responses)
    if case.report_response is not None:
        structured_responses[InvestigationReport] = [case.report_response]

    llm = RecordingFakeAgentLLM(
        tool_call_script=case.tool_call_script, structured_responses=structured_responses
    )

    report = None
    incomplete_reason = None
    try:
        report = await run_investigation(ctx, incident_id, llm)
    except InvestigationIncomplete as exc:
        incomplete_reason = exc.reason

    incident_after = None
    episode_items: list[dict] = []
    remediation_proposals: list = []
    if case.incident_id_override is None:
        incident_after = await IncidentRepository(db).get_by_id(
            tenant_id=fixtures.tenant.id, incident_id=incident_id
        )
        episode = await EpisodeRepository(db).get_latest_for_incident(
            tenant_id=fixtures.tenant.id, incident_id=incident_id
        )
        if episode is not None:
            episode_items = episode.evidence.get("items", [])
        remediation_proposals = await RemediationRepository(db).list_for_incident(
            tenant_id=fixtures.tenant.id, incident_id=incident_id
        )

    outcome = EvalOutcome(
        case=case,
        fixtures=fixtures,
        db=db,
        llm=llm,
        incident=incident_after,
        report=report,
        incomplete_reason=incomplete_reason,
        episode_evidence_items=episode_items,
        remediation_proposals=remediation_proposals,
    )

    results: list[CheckResult] = []
    for evaluator in case.evaluators:
        results.extend(evaluator(outcome))
    return results


async def _run_all() -> dict[str, Any]:
    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        fixtures = await build_fixtures(db)
        try:
            cases = build_golden_cases(fixtures)
            case_reports: list[dict[str, Any]] = []
            for case in cases:
                try:
                    results = await _run_one_case(db, fixtures, case)
                except Exception as exc:  # noqa: BLE001 - a crashed case is a failed case, not a skipped one
                    results = [
                        CheckResult(
                            name="case_raised_unexpectedly",
                            passed=False,
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                    ]
                case_reports.append(
                    {
                        "id": case.id,
                        "category": case.category,
                        "description": case.description,
                        "checks": [asdict(r) for r in results],
                        "passed": all(r.passed for r in results),
                    }
                )
        finally:
            await teardown_fixtures(db, fixtures)

    total_checks = sum(len(c["checks"]) for c in case_reports)
    failed_checks = sum(1 for c in case_reports for check in c["checks"] if not check["passed"])
    return {
        "cases": case_reports,
        "case_count": len(case_reports),
        "cases_passed": sum(1 for c in case_reports if c["passed"]),
        "total_checks": total_checks,
        "failed_checks": failed_checks,
        "duration_seconds": round(time.monotonic() - started, 2),
    }


def _print_report(report: dict[str, Any]) -> None:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for case in report["cases"]:
        by_category.setdefault(case["category"], []).append(case)

    for category, cases in sorted(by_category.items()):
        passed = sum(1 for c in cases if c["passed"])
        print(f"\n{category} ({passed}/{len(cases)} cases passed)")
        for case in cases:
            marker = "PASS" if case["passed"] else "FAIL"
            print(f"  [{marker}] {case['id']}: {case['description']}")
            if not case["passed"]:
                for check in case["checks"]:
                    if not check["passed"]:
                        print(f"           - {check['name']}: {check['detail']}")

    print(
        f"\n{report['cases_passed']}/{report['case_count']} cases passed, "
        f"{report['total_checks'] - report['failed_checks']}/{report['total_checks']} "
        f"checks passed, in {report['duration_seconds']}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=None, help="Write the full report as JSON")
    args = parser.parse_args()

    report = asyncio.run(_run_all())
    _print_report(report)

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nFull report written to {args.json_out}")

    return 0 if report["failed_checks"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
