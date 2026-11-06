import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

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
from app.observability.tracing import investigation_trace
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
    with investigation_trace(
        tenant_id=ctx.tenant_id, user_id=ctx.user.id, incident_id=incident_id
    ) as root_span:
        # mypy can't resolve this against langgraph 1.x's Pregel.ainvoke
        # overload set (confirmed this exact call shape runs correctly at
        # runtime — see the comment in nodes/intake.py for the same
        # library's typing friction).
        final_state = await compiled.ainvoke(  # type: ignore[call-overload]
            {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "incident_id": incident_id},
            config=config,
        )

        if final_state.get("error"):
            root_span.update(level="ERROR", status_message=final_state["error"])
            raise InvestigationIncomplete(final_state["error"])

        report = final_state.get("report")
        if report is None:
            root_span.update(level="ERROR", status_message="no report produced")
            raise InvestigationIncomplete("investigation ended without producing a report")

        root_span.update(output=report.model_dump(mode="json"))
        return report


@dataclass(frozen=True)
class InvestigationStreamEvent:
    event: str  # "node_complete" | "report" | "error"
    data: dict[str, Any]


async def stream_investigation(
    ctx: ToolContext, incident_id: uuid.UUID, llm: AgentLLM
) -> AsyncIterator[InvestigationStreamEvent]:
    """Same graph, same bounds, same tracing as run_investigation — this
    surfaces progress as it happens instead of blocking until the whole
    investigation finishes, so an SSE client can show "gathering
    evidence..." rather than a blank wait for however long the LLM round
    trips take.
    """
    compiled = build_graph(ctx, llm)
    config = {
        "configurable": {"thread_id": str(incident_id)},
        "recursion_limit": _RECURSION_LIMIT,
    }
    with investigation_trace(
        tenant_id=ctx.tenant_id, user_id=ctx.user.id, incident_id=incident_id
    ) as root_span:
        try:
            async for update in compiled.astream(  # type: ignore[call-overload]
                {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "incident_id": incident_id},
                config=config,
                stream_mode="updates",
            ):
                for node_name, node_output in update.items():
                    yield InvestigationStreamEvent(event="node_complete", data={"node": node_name})

                    if node_name == "intake" and node_output.get("error"):
                        root_span.update(level="ERROR", status_message=node_output["error"])
                        yield InvestigationStreamEvent(
                            event="error", data={"message": node_output["error"]}
                        )
                        return

                    if node_name == "report" and node_output.get("report") is not None:
                        report = node_output["report"]
                        root_span.update(output=report.model_dump(mode="json"))
                        yield InvestigationStreamEvent(
                            event="report", data=report.model_dump(mode="json")
                        )
        except Exception as exc:
            root_span.update(level="ERROR", status_message=str(exc))
            yield InvestigationStreamEvent(
                event="error", data={"message": "investigation failed unexpectedly"}
            )
