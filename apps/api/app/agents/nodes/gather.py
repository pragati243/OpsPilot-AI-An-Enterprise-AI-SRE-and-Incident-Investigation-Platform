from datetime import UTC, datetime

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from app.agents.llm_client import AgentLLM
from app.agents.prompts import GATHER_SYSTEM_PROMPT
from app.agents.schemas import EvidenceItem
from app.agents.state import InvestigationState


# See the comment in nodes/intake.py about why these builders don't carry an
# explicit Callable[...] return annotation.
def build_agent_node(llm: AgentLLM, tools: dict[str, StructuredTool]):
    async def agent_node(state: InvestigationState) -> dict:
        existing = state.get("messages") or []
        new_messages: list[AnyMessage] = []

        if not existing:
            plan = state.get("plan")
            plan_lines = (
                "\n".join(f"- {s.tool}: {s.reason}" for s in plan.steps)
                if plan and plan.steps
                else "(none)"
            )
            intro = (
                f"Incident: {state['incident_title']}\n"
                f"Service: {state['service']} (environment: {state['environment']})\n"
                f"Initial hypothesis: {plan.hypothesis if plan else 'none yet'}\n"
                f"Suggested first steps:\n{plan_lines}"
            )
            new_messages.extend(
                [SystemMessage(content=GATHER_SYSTEM_PROMPT), HumanMessage(content=intro)]
            )

        if state.get("tool_call_count", 0) >= state["max_tool_calls"]:
            # Budget already exhausted by a prior iteration — don't spend
            # another model call, just fall through to assess.
            return {"messages": new_messages}

        if datetime.now(UTC) >= state["deadline"]:
            return {"messages": new_messages}

        response = await llm.call_with_tools([*existing, *new_messages], list(tools.values()))
        new_messages.append(response)
        return {"messages": new_messages}

    return agent_node


def build_execute_tools_node(tools: dict[str, StructuredTool]):
    async def execute_tools(state: InvestigationState) -> dict:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        tool_calls = last.tool_calls if isinstance(last, AIMessage) else []

        remaining_budget = max(0, state["max_tool_calls"] - state.get("tool_call_count", 0))
        calls_to_run = tool_calls[:remaining_budget]
        calls_over_budget = tool_calls[remaining_budget:]

        new_messages: list[AnyMessage] = []
        new_evidence: list[EvidenceItem] = []

        for call in calls_to_run:
            tool = tools.get(call["name"])
            if tool is None:
                result = {"error": f"unknown tool {call['name']!r}"}
            else:
                result = await tool.ainvoke(call["args"])
                if not isinstance(result, dict):
                    result = {"value": result}

            new_messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
            new_evidence.append(
                EvidenceItem(
                    tool=call["name"],
                    input=call["args"],
                    output=result,
                    timestamp=datetime.now(UTC),
                    error=result.get("error"),
                )
            )

        for call in calls_over_budget:
            new_messages.append(
                ToolMessage(
                    content=str({"error": "tool-call budget exhausted for this investigation"}),
                    tool_call_id=call["id"],
                )
            )

        return {
            "messages": new_messages,
            "evidence": new_evidence,
            "tool_call_count": state.get("tool_call_count", 0) + len(calls_to_run),
            "gather_iteration": state.get("gather_iteration", 0) + 1,
        }

    return execute_tools


def route_after_agent(state: InvestigationState) -> str:
    messages = state.get("messages") or []
    if not messages:
        return "assess"
    last = messages[-1]
    has_pending_tool_calls = isinstance(last, AIMessage) and bool(last.tool_calls)
    budget_remaining = state.get("tool_call_count", 0) < state["max_tool_calls"]
    if has_pending_tool_calls and budget_remaining:
        return "execute_tools"
    return "assess"
