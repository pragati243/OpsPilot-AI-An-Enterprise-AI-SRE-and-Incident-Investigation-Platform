from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_client import AgentLLM
from app.agents.prompts import ASSESS_SYSTEM_PROMPT
from app.agents.schemas import Assessment
from app.agents.state import InvestigationState


# See the comment in nodes/intake.py about why these builders don't carry an
# explicit Callable[...] return annotation.
def build_assess_node(llm: AgentLLM):
    async def assess(state: InvestigationState) -> dict:
        evidence = state.get("evidence") or []
        evidence_text = (
            "\n".join(
                f"- {e.tool}({e.input}) -> {e.output}"
                + (f" [ERROR: {e.error}]" if e.error else "")
                for e in evidence
            )
            or "(no evidence gathered)"
        )
        prompt = (
            f"Incident: {state['incident_title']} on {state['service']} "
            f"({state['environment']})\n\nEvidence gathered so far:\n{evidence_text}"
        )
        messages = [SystemMessage(content=ASSESS_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        assessment = await llm.call_structured(messages, Assessment)
        return {"assessment": assessment}

    return assess


def route_after_assess(state: InvestigationState) -> str:
    """Confidence and safety gate: report once ready, or once bounds are
    exhausted — an unbounded retry loop is exactly what the workflow spec
    rules out.
    """
    assessment = state.get("assessment")
    ready = bool(assessment and assessment.ready_to_report)
    budget_exhausted = state.get("tool_call_count", 0) >= state["max_tool_calls"]
    iterations_exhausted = state.get("gather_iteration", 0) >= state["max_gather_iterations"]
    if ready or budget_exhausted or iterations_exhausted:
        return "report"
    return "agent"
