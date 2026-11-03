from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm_client import AgentLLM
from app.agents.prompts import PLAN_SYSTEM_PROMPT
from app.agents.schemas import InvestigationPlan
from app.agents.state import InvestigationState


# See the comment in nodes/intake.py about why these builders don't carry an
# explicit Callable[...] return annotation.
def build_plan_node(llm: AgentLLM):
    async def plan(state: InvestigationState) -> dict:
        prompt = (
            f"Incident: {state['incident_title']}\n"
            f"Service: {state['service']} (environment: {state['environment']})\n"
            "Available tools: get_service_health, query_logs, get_service_metrics, "
            "search_runbooks, search_past_incidents."
        )
        messages = [SystemMessage(content=PLAN_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        investigation_plan = await llm.call_structured(messages, InvestigationPlan)
        return {"plan": investigation_plan}

    return plan
