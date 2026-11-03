import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.llm_client import AgentLLM
from app.agents.nodes.assess import build_assess_node, route_after_assess
from app.agents.nodes.gather import build_agent_node, build_execute_tools_node, route_after_agent
from app.agents.nodes.intake import build_intake_node, route_after_intake
from app.agents.nodes.plan import build_plan_node
from app.agents.nodes.report import build_report_node
from app.agents.schemas import InvestigationReport
from app.agents.state import InvestigationState
from app.agents.tool_adapter import build_tools_for_context
from app.tools.context import ToolContext

# Comfortably above the worst case (intake + plan + up to ~8 agent/tool
# round trips bounded by max_tool_calls + assess/report), without being
# unbounded.
_RECURSION_LIMIT = 50


class InvestigationIncomplete(Exception):
    """Raised when the graph ends without a report — e.g. intake rejected
    an unknown or cross-tenant incident_id before any model call happened.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def build_graph(ctx: ToolContext, llm: AgentLLM) -> CompiledStateGraph:
    tools = build_tools_for_context(ctx)

    graph = StateGraph(InvestigationState)
    graph.add_node("intake", build_intake_node(ctx))
    graph.add_node("plan", build_plan_node(ctx, llm))
    graph.add_node("agent", build_agent_node(llm, tools))
    graph.add_node("execute_tools", build_execute_tools_node(tools))
    graph.add_node("assess", build_assess_node(llm))
    graph.add_node("report", build_report_node(ctx, llm))

    graph.add_edge(START, "intake")
    graph.add_conditional_edges("intake", route_after_intake, {"plan": "plan", "end": END})
    graph.add_edge("plan", "agent")
    graph.add_conditional_edges(
        "agent", route_after_agent, {"execute_tools": "execute_tools", "assess": "assess"}
    )
    graph.add_edge("execute_tools", "agent")
    graph.add_conditional_edges(
        "assess", route_after_assess, {"report": "report", "agent": "agent"}
    )
    graph.add_edge("report", END)

    return graph.compile(checkpointer=InMemorySaver())


async def run_investigation(
    ctx: ToolContext, incident_id: uuid.UUID, llm: AgentLLM
) -> InvestigationReport:
    compiled = build_graph(ctx, llm)
    config = {
        "configurable": {"thread_id": str(incident_id)},
        "recursion_limit": _RECURSION_LIMIT,
    }
    # mypy can't resolve this against langgraph 1.x's Pregel.ainvoke overload
    # set (confirmed this exact call shape runs correctly at runtime — see
    # the comment in nodes/intake.py for the same library's typing friction).
    final_state = await compiled.ainvoke(  # type: ignore[call-overload]
        {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "incident_id": incident_id},
        config=config,
    )

    if final_state.get("error"):
        raise InvestigationIncomplete(final_state["error"])

    report = final_state.get("report")
    if report is None:
        raise InvestigationIncomplete("investigation ended without producing a report")
    return report
