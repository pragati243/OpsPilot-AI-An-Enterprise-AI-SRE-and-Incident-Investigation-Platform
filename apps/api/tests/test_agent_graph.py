import uuid

import pytest
from sqlalchemy import select

from app.agents.graph import InvestigationIncomplete, build_graph, run_investigation
from app.agents.schemas import (
    Assessment,
    InvestigationPlan,
    InvestigationReport,
    PlannedStep,
    RecommendedAction,
)
from app.memory.schemas import ExtractedMemories, MemoryCandidate
from app.models.incident import IncidentSeverity, IncidentStatus
from app.models.memory import MemoryRecord, MemoryStatus
from app.models.remediation import RemediationProposal, RemediationStatus
from app.models.service import ServiceStatus
from app.repositories.incident_repository import IncidentRepository
from app.repositories.service_repository import ServiceRepository
from app.tools.context import ToolContext
from tests.fakes import FakeAgentLLM, tool_call

PLAN = InvestigationPlan(
    hypothesis="Possible DB connection pool exhaustion",
    steps=[PlannedStep(tool="get_service_health", reason="check current status")],
)


async def _seed_service(ctx: ToolContext) -> None:
    await ServiceRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        name="checkout-service",
        environment="production",
        description="test service",
        owner_team="test-team",
        status=ServiceStatus.DEGRADED,
        scenario_tag="db_connection_pool_exhaustion",
    )


async def _seed_incident(ctx: ToolContext):
    return await IncidentRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        title="Checkout error rate elevated",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.INVESTIGATING,
        created_by=ctx.user.id,
    )


async def test_happy_path_produces_report_and_persists_episode(
    tool_ctx: ToolContext,
) -> None:
    await _seed_service(tool_ctx)
    incident = await _seed_incident(tool_ctx)

    llm = FakeAgentLLM(
        tool_call_script=[
            [tool_call("get_service_health", {"service": "checkout-service"}, "call_1")],
            [],
        ],
        structured_responses={
            InvestigationPlan: [PLAN],
            Assessment: [
                Assessment(
                    leading_hypothesis="DB connection pool exhaustion",
                    supporting_evidence=["get_service_health showed degraded status"],
                    confidence=0.85,
                    missing_evidence=[],
                    ready_to_report=True,
                )
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Connection pool exhausted under peak load.",
                    evidence_summary="Health check showed degraded status with high error rate.",
                    resolution=None,
                    citations=["get_service_health"],
                    confidence=0.85,
                    outcome="resolved",
                    recommended_actions=[],
                )
            ],
        },
    )

    report = await run_investigation(tool_ctx, incident.id, llm)

    assert report.outcome == "resolved"
    assert "connection pool" in report.diagnosis.lower()

    refreshed = await IncidentRepository(tool_ctx.db).get_by_id(
        tenant_id=tool_ctx.tenant_id, incident_id=incident.id
    )
    assert refreshed is not None
    assert refreshed.status == IncidentStatus.RESOLVED
    assert refreshed.resolved_at is not None


async def test_insufficient_evidence_reports_unresolved_not_fabricated(
    tool_ctx: ToolContext,
) -> None:
    await _seed_service(tool_ctx)
    incident = await _seed_incident(tool_ctx)

    llm = FakeAgentLLM(
        tool_call_script=[[]],  # agent decides it has nothing more to check immediately
        structured_responses={
            InvestigationPlan: [PLAN],
            Assessment: [
                Assessment(
                    leading_hypothesis="Unclear",
                    supporting_evidence=[],
                    confidence=0.1,
                    missing_evidence=["logs", "metrics"],
                    ready_to_report=True,
                )
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Evidence gathered was insufficient to determine a root cause.",
                    evidence_summary="No tool calls completed before the budget was spent.",
                    resolution=None,
                    citations=[],
                    confidence=0.1,
                    outcome="unresolved",
                    recommended_actions=[],
                    uncertainty_note="Need logs and metrics to proceed.",
                )
            ],
        },
    )

    report = await run_investigation(tool_ctx, incident.id, llm)

    assert report.outcome == "unresolved"
    assert report.uncertainty_note

    refreshed = await IncidentRepository(tool_ctx.db).get_by_id(
        tenant_id=tool_ctx.tenant_id, incident_id=incident.id
    )
    assert refreshed is not None
    assert refreshed.status == IncidentStatus.INVESTIGATING
    assert refreshed.resolved_at is None


async def test_tool_call_budget_is_enforced(tool_ctx: ToolContext) -> None:
    await _seed_service(tool_ctx)
    incident = await _seed_incident(tool_ctx)

    # Script far more tool calls than the budget allows; if bounding is
    # broken this would call the LLM many more times than expected.
    unbounded_script = [
        [tool_call("get_service_health", {"service": "checkout-service"}, f"call_{i}")]
        for i in range(20)
    ]
    llm = FakeAgentLLM(
        tool_call_script=unbounded_script,
        structured_responses={
            InvestigationPlan: [PLAN],
            Assessment: [
                Assessment(
                    leading_hypothesis="n/a",
                    confidence=0.3,
                    missing_evidence=["more evidence than budget allowed"],
                    ready_to_report=True,
                )
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Evidence insufficient within the tool-call budget.",
                    evidence_summary="Budget exhausted.",
                    resolution=None,
                    citations=[],
                    confidence=0.3,
                    outcome="unresolved",
                    recommended_actions=[],
                    uncertainty_note="Ran out of tool-call budget.",
                )
            ],
        },
    )

    compiled = build_graph(tool_ctx, llm)
    final_state = await compiled.ainvoke(  # type: ignore[call-overload]
        {
            "tenant_id": tool_ctx.tenant_id,
            "user_id": tool_ctx.user.id,
            "incident_id": incident.id,
            "max_tool_calls": 3,
            "max_gather_iterations": 10,
        },
        config={"configurable": {"thread_id": str(incident.id)}, "recursion_limit": 100},
    )

    assert final_state["tool_call_count"] <= 3
    assert len(final_state["evidence"]) <= 3
    assert final_state["report"] is not None


async def test_unauthorized_incident_raises_without_calling_llm(
    tool_ctx: ToolContext,
) -> None:
    llm = FakeAgentLLM()

    with pytest.raises(InvestigationIncomplete):
        await run_investigation(tool_ctx, uuid.uuid4(), llm)

    assert llm.call_with_tools_count == 0
    assert llm.call_structured_count == 0


async def test_recommended_action_creates_pending_remediation_proposal(
    tool_ctx: ToolContext,
) -> None:
    await _seed_service(tool_ctx)
    incident = await _seed_incident(tool_ctx)

    llm = FakeAgentLLM(
        tool_call_script=[[]],
        structured_responses={
            InvestigationPlan: [PLAN],
            Assessment: [
                Assessment(
                    leading_hypothesis="DB connection pool exhaustion",
                    confidence=0.8,
                    ready_to_report=True,
                )
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Connection pool exhausted.",
                    evidence_summary="n/a",
                    resolution=None,
                    citations=[],
                    confidence=0.8,
                    outcome="resolved",
                    recommended_actions=[
                        RecommendedAction(
                            action_type="restart_service", rationale="Clear stuck connections"
                        )
                    ],
                )
            ],
        },
    )

    await run_investigation(tool_ctx, incident.id, llm)

    proposal = await tool_ctx.db.scalar(
        select(RemediationProposal).where(RemediationProposal.incident_id == incident.id)
    )
    assert proposal is not None
    assert proposal.status == RemediationStatus.PENDING_APPROVAL
    assert proposal.action_type == "restart_service"


async def test_recommended_action_outside_allowlist_does_not_crash_report(
    tool_ctx: ToolContext,
) -> None:
    await _seed_service(tool_ctx)
    incident = await _seed_incident(tool_ctx)

    llm = FakeAgentLLM(
        tool_call_script=[[]],
        structured_responses={
            InvestigationPlan: [PLAN],
            Assessment: [
                Assessment(leading_hypothesis="n/a", confidence=0.8, ready_to_report=True)
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Connection pool exhausted.",
                    evidence_summary="n/a",
                    resolution=None,
                    citations=[],
                    confidence=0.8,
                    outcome="resolved",
                    recommended_actions=[
                        RecommendedAction(
                            action_type="drop_production_database",
                            rationale="This should never be allowed through",
                        )
                    ],
                )
            ],
        },
    )

    report = await run_investigation(tool_ctx, incident.id, llm)
    assert report.outcome == "resolved"

    proposal = await tool_ctx.db.scalar(
        select(RemediationProposal).where(RemediationProposal.incident_id == incident.id)
    )
    assert proposal is None


async def test_tool_error_is_captured_as_evidence_not_a_crash(tool_ctx: ToolContext) -> None:
    incident = await _seed_incident(tool_ctx)
    # Deliberately no service seeded — get_service_health will raise
    # ServiceNotFoundError, which the tool adapter must turn into a clean
    # {"error": ...} result rather than letting it blow up the graph.

    llm = FakeAgentLLM(
        tool_call_script=[
            [tool_call("get_service_health", {"service": "checkout-service"}, "call_1")],
            [],
        ],
        structured_responses={
            InvestigationPlan: [PLAN],
            Assessment: [
                Assessment(
                    leading_hypothesis="n/a",
                    confidence=0.0,
                    missing_evidence=["service lookup failed"],
                    ready_to_report=True,
                )
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Could not look up the service; evidence insufficient.",
                    evidence_summary="Tool call failed.",
                    resolution=None,
                    citations=[],
                    confidence=0.0,
                    outcome="unresolved",
                    recommended_actions=[],
                    uncertainty_note="Service lookup failed.",
                )
            ],
        },
    )

    report = await run_investigation(tool_ctx, incident.id, llm)
    assert report.outcome == "unresolved"


def _llm_for_monday_friday(hypothesis: str) -> FakeAgentLLM:
    return FakeAgentLLM(
        tool_call_script=[[]],
        structured_responses={
            InvestigationPlan: [InvestigationPlan(hypothesis=hypothesis, steps=[])],
            Assessment: [
                Assessment(leading_hypothesis=hypothesis, confidence=0.85, ready_to_report=True)
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="Connection pool exhausted under peak load.",
                    evidence_summary="Health degraded, elevated error rate.",
                    resolution=None,
                    citations=[],
                    confidence=0.85,
                    outcome="resolved",
                    recommended_actions=[],
                )
            ],
            ExtractedMemories: [
                ExtractedMemories(
                    candidates=[
                        MemoryCandidate(
                            memory_type="semantic",
                            content="checkout-service uses a Postgres connection pool sized at 10.",
                            confidence=0.9,
                        )
                    ]
                )
            ],
        },
    )


async def test_monday_friday_scenario_recalls_and_supersedes_memory(
    tool_ctx: ToolContext,
) -> None:
    """The spec's worked example: Monday's resolved incident becomes a
    memory; Friday's similar incident recalls it during planning (verified
    separately in test_plan_prompt_includes_recalled_memory below) and,
    once resolved the same way, supersedes rather than duplicates it.
    """
    await _seed_service(tool_ctx)
    monday_incident = await _seed_incident(tool_ctx)

    await run_investigation(tool_ctx, monday_incident.id, _llm_for_monday_friday("Monday"))

    active_after_monday = (
        await tool_ctx.db.execute(
            select(MemoryRecord).where(
                MemoryRecord.tenant_id == tool_ctx.tenant_id,
                MemoryRecord.status == MemoryStatus.ACTIVE,
            )
        )
    ).scalars().all()
    assert len(active_after_monday) == 1

    friday_incident = await IncidentRepository(tool_ctx.db).create(
        tenant_id=tool_ctx.tenant_id,
        title="Checkout error rate elevated again",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.INVESTIGATING,
        created_by=tool_ctx.user.id,
    )
    await run_investigation(tool_ctx, friday_incident.id, _llm_for_monday_friday("Friday"))

    all_memories = (
        await tool_ctx.db.execute(
            select(MemoryRecord).where(MemoryRecord.tenant_id == tool_ctx.tenant_id)
        )
    ).scalars().all()
    active = [m for m in all_memories if m.status == MemoryStatus.ACTIVE]
    superseded = [m for m in all_memories if m.status == MemoryStatus.SUPERSEDED]
    assert len(active) == 1
    assert len(superseded) == 1
    assert superseded[0].superseded_by == active[0].id


async def test_plan_prompt_includes_recalled_memory_with_verify_instruction(
    tool_ctx: ToolContext,
) -> None:
    """Confirms recall actually reaches the plan node's prompt (not just
    that storage/supersession works) and that it's framed as something to
    verify, not assume.
    """
    await _seed_service(tool_ctx)
    first_incident = await _seed_incident(tool_ctx)
    await run_investigation(tool_ctx, first_incident.id, _llm_for_monday_friday("first"))

    class RecordingFakeLLM(FakeAgentLLM):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.plan_prompts: list[str] = []

        async def call_structured(self, messages, schema):
            if schema is InvestigationPlan:
                self.plan_prompts.append(str(messages[-1].content))
            return await super().call_structured(messages, schema)

    second_incident = await IncidentRepository(tool_ctx.db).create(
        tenant_id=tool_ctx.tenant_id,
        title="Checkout error rate elevated again",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.INVESTIGATING,
        created_by=tool_ctx.user.id,
    )
    llm = RecordingFakeLLM(
        tool_call_script=[[]],
        structured_responses={
            InvestigationPlan: [InvestigationPlan(hypothesis="n/a", steps=[])],
            Assessment: [
                Assessment(leading_hypothesis="n/a", confidence=0.5, ready_to_report=True)
            ],
            InvestigationReport: [
                InvestigationReport(
                    diagnosis="n/a",
                    evidence_summary="n/a",
                    resolution=None,
                    citations=[],
                    confidence=0.5,
                    outcome="unresolved",
                    recommended_actions=[],
                )
            ],
        },
    )
    await run_investigation(tool_ctx, second_incident.id, llm)

    assert len(llm.plan_prompts) == 1
    prompt = llm.plan_prompts[0]
    assert "connection pool" in prompt.lower()
    assert "verify" in prompt.lower()
