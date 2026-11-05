from langchain_core.messages import HumanMessage, SystemMessage
from langfuse import observe

from app.agents.llm_client import AgentLLM
from app.agents.prompts import PLAN_SYSTEM_PROMPT
from app.agents.schemas import InvestigationPlan
from app.agents.state import InvestigationState
from app.memory.recall import recall_memories
from app.observability.client import get_langfuse_client
from app.tools.context import ToolContext


# See the comment in nodes/intake.py about why these builders don't carry an
# explicit Callable[...] return annotation.
def build_plan_node(ctx: ToolContext, llm: AgentLLM):
    @observe(name="node:plan", as_type="span", capture_input=False, capture_output=False)
    async def plan(state: InvestigationState) -> dict:
        memories = await recall_memories(
            ctx.db,
            tenant_id=ctx.tenant_id,
            user_id=None,
            query=f"{state['service']} {state['incident_title']}",
            limit=5,
        )
        memory_text = (
            "\n".join(f"- {m.content} (confidence {m.confidence:.2f})" for m in memories)
            if memories
            else "(none)"
        )

        prompt = (
            f"Incident: {state['incident_title']}\n"
            f"Service: {state['service']} (environment: {state['environment']})\n"
            "Available tools: get_service_health, query_logs, get_service_metrics, "
            "search_runbooks, search_past_incidents.\n"
            f"Remembered facts about this service (verify, don't assume):\n{memory_text}"
        )
        messages = [SystemMessage(content=PLAN_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        investigation_plan = await llm.call_structured(messages, InvestigationPlan)

        get_langfuse_client().update_current_span(
            input={"service": state["service"], "recalled_memory_count": len(memories)},
            output={
                "hypothesis": investigation_plan.hypothesis,
                "planned_steps": [s.tool for s in investigation_plan.steps],
            },
        )
        return {"plan": investigation_plan}

    return plan
