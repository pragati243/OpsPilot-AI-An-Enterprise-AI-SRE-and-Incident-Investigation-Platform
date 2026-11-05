from langchain_core.messages import HumanMessage, SystemMessage
from langfuse import observe

from app.agents.llm_client import AgentLLM
from app.agents.prompts import REPORT_SYSTEM_PROMPT
from app.agents.schemas import InvestigationReport
from app.agents.state import InvestigationState
from app.core.logging import get_logger
from app.guardrails.action_allowlist import ActionNotAllowedError
from app.memory.extraction import extract_and_store_memories
from app.models.episode import EpisodeOutcome
from app.models.memory import MemoryType
from app.observability.client import get_langfuse_client
from app.repositories.memory_repository import MemoryRepository
from app.tools.context import ToolContext
from app.tools.remediation import propose_remediation
from app.tools.reporting import create_incident_report
from app.tools.schemas import CreateIncidentReportInput, ProposeRemediationInput

logger = get_logger(__name__)


# See the comment in nodes/intake.py about why these builders don't carry an
# explicit Callable[...] return annotation.
def build_report_node(ctx: ToolContext, llm: AgentLLM):
    @observe(name="node:report", as_type="span", capture_input=False, capture_output=False)
    async def report(state: InvestigationState) -> dict:
        assessment = state.get("assessment")
        evidence = state.get("evidence") or []
        evidence_text = (
            "\n".join(
                f"- {e.tool}({e.input}) -> {e.output}"
                + (f" [ERROR: {e.error}]" if e.error else "")
                for e in evidence
            )
            or "(no evidence gathered)"
        )
        assessment_text = (
            (
                f"Leading hypothesis: {assessment.leading_hypothesis}\n"
                f"Confidence: {assessment.confidence}\n"
                f"Missing evidence: {', '.join(assessment.missing_evidence) or 'none noted'}"
            )
            if assessment
            else "(no assessment was completed — bounds were likely exhausted early)"
        )

        profile_memories = await MemoryRepository(ctx.db).list_active(
            tenant_id=ctx.tenant_id, user_id=ctx.user.id, memory_type=MemoryType.PROFILE
        )
        profile_text = (
            "\n".join(f"- {m.content}" for m in profile_memories)
            if profile_memories
            else "(none stated)"
        )

        prompt = (
            f"Incident: {state['incident_title']} on {state['service']} "
            f"({state['environment']})\n\n"
            f"Evidence:\n{evidence_text}\n\nAssessment:\n{assessment_text}\n\n"
            f"Investigating engineer's stated preferences:\n{profile_text}"
        )
        messages = [SystemMessage(content=REPORT_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        investigation_report = await llm.call_structured(messages, InvestigationReport)

        # Deterministic, app-controlled persistence: the model produced a
        # structured report, but it is this code — not the model — that
        # decides create_incident_report and propose_remediation actually
        # run, and propose_remediation still only ever lands pending approval.
        report_result = await create_incident_report(
            ctx,
            CreateIncidentReportInput(
                incident_id=state["incident_id"],
                diagnosis=investigation_report.diagnosis,
                evidence={"items": [e.model_dump(mode="json") for e in evidence]},
                resolution=investigation_report.resolution,
                outcome=EpisodeOutcome(investigation_report.outcome),
                confidence=investigation_report.confidence,
                citations=investigation_report.citations,
            ),
        )

        for action in investigation_report.recommended_actions:
            try:
                await propose_remediation(
                    ctx,
                    ProposeRemediationInput(
                        incident_id=state["incident_id"],
                        action_type=action.action_type,
                        action_params={},
                        rationale=action.rationale,
                    ),
                )
            except ActionNotAllowedError:
                logger.warning(
                    "recommended_action_not_in_allowlist",
                    action_type=action.action_type,
                    incident_id=str(state["incident_id"]),
                )

        try:
            await extract_and_store_memories(
                ctx.db,
                tenant_id=ctx.tenant_id,
                source_episode_id=report_result.episode_id,
                llm=llm,
                incident_title=state["incident_title"],
                service=state["service"],
                diagnosis=investigation_report.diagnosis,
                evidence_summary=investigation_report.evidence_summary,
            )
        except Exception:
            # Learning from this investigation is a bonus, not a
            # requirement — a broken extraction call must never fail an
            # otherwise-successful investigation that already has a report.
            logger.warning(
                "memory_extraction_failed", incident_id=str(state["incident_id"]), exc_info=True
            )

        get_langfuse_client().update_current_span(
            input={"evidence_count": len(evidence)},
            output={
                "outcome": investigation_report.outcome,
                "confidence": investigation_report.confidence,
                "recommended_action_count": len(investigation_report.recommended_actions),
            },
        )
        return {"report": investigation_report}

    return report
