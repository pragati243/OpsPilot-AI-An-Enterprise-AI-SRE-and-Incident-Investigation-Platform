from datetime import UTC, datetime, timedelta

from app.agents.state import InvestigationState
from app.repositories.incident_repository import IncidentRepository
from app.tools.context import ToolContext

DEFAULT_MAX_TOOL_CALLS = 8
DEFAULT_MAX_GATHER_ITERATIONS = 3
DEFAULT_DEADLINE_SECONDS = 90


# No explicit Callable[...] return annotation on build_* node functions
# below: mypy's structural match against LangGraph's _Node protocol only
# succeeds when it infers the callable type from the nested `async def`
# directly. An explicit Callable[[State], Awaitable[dict]] annotation here
# makes `graph.add_node(...)` fail to resolve any overload — confirmed by
# isolated repro against this langgraph version, not a runtime issue.
def build_intake_node(ctx: ToolContext):
    async def intake(state: InvestigationState) -> dict:
        """Validate the incident exists and belongs to this tenant before any
        LLM call happens — an unauthorized or bogus incident_id costs nothing
        beyond one DB lookup, never a model call.
        """
        incident = await IncidentRepository(ctx.db).get_by_id(
            tenant_id=ctx.tenant_id, incident_id=state["incident_id"]
        )
        if incident is None:
            return {
                "authorized": False,
                "error": "incident not found, or not accessible to this tenant",
            }

        return {
            "authorized": True,
            "incident_title": incident.title,
            "service": incident.service,
            "environment": incident.environment,
            "max_tool_calls": state.get("max_tool_calls") or DEFAULT_MAX_TOOL_CALLS,
            "max_gather_iterations": (
                state.get("max_gather_iterations") or DEFAULT_MAX_GATHER_ITERATIONS
            ),
            "deadline": state.get("deadline")
            or datetime.now(UTC) + timedelta(seconds=DEFAULT_DEADLINE_SECONDS),
            "tool_call_count": 0,
            "gather_iteration": 0,
        }

    return intake


def route_after_intake(state: InvestigationState) -> str:
    return "plan" if state.get("authorized") else "end"
