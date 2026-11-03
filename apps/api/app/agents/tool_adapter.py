from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.tools.context import ToolContext
from app.tools.exceptions import ToolError
from app.tools.health import get_service_health
from app.tools.incidents import search_past_incidents
from app.tools.logs import query_logs
from app.tools.metrics import get_service_metrics
from app.tools.runbooks import search_runbooks
from app.tools.schemas import (
    GetServiceHealthInput,
    GetServiceMetricsInput,
    QueryLogsInput,
    SearchPastIncidentsInput,
    SearchRunbooksInput,
)
from app.tools.time_window import InvalidTimeWindowError

ToolFn = Callable[[ToolContext, BaseModel], Awaitable[BaseModel]]
# Each tuple's fn only ever gets called with an instance of its own schema
# (see the loop below), but the 5 tool functions have mutually incompatible
# narrower signatures, so mypy can't type this list any tighter than Any
# without losing that per-row pairing.
_ToolDef = tuple[str, str, type[BaseModel], Callable[..., Awaitable[Any]]]

# Only the read-only diagnostic/knowledge tools are exposed to the LLM's own
# tool-calling loop. The mutating tools (create_incident_report,
# propose_remediation) are deliberately never handed to the model — the
# report node calls them itself, deterministically, from the model's
# structured output. The model can suggest; it cannot invoke a mutation.
_TOOL_DEFS: list[_ToolDef] = [
    (
        "get_service_health",
        "Get the current health status and a symptom-level summary for a service.",
        GetServiceHealthInput,
        get_service_health,
    ),
    (
        "query_logs",
        "Query recent logs for a service, filtered by a minimum severity "
        "(debug/info/warn/error/critical). time_window looks like '15m', '1h', or '2d'.",
        QueryLogsInput,
        query_logs,
    ),
    (
        "get_service_metrics",
        "Get latency (p50/p95/p99), error rate, request rate, cpu, and memory for a "
        "service over a time window like '15m', '1h', or '2d'.",
        GetServiceMetricsInput,
        get_service_metrics,
    ),
    (
        "search_runbooks",
        "Search runbooks for diagnostic guidance relevant to a free-text query.",
        SearchRunbooksInput,
        search_runbooks,
    ),
    (
        "search_past_incidents",
        "Search previously recorded incidents for similar evidence, diagnoses, "
        "and resolutions.",
        SearchPastIncidentsInput,
        search_past_incidents,
    ),
]


def build_tools_for_context(ctx: ToolContext) -> dict[str, StructuredTool]:
    """One StructuredTool per read-only tool, bound to this request's
    ToolContext via closure. Returned as a name-keyed dict so the gather
    node can both `.bind_tools(list(tools.values()))` for the LLM's schema
    and look a specific tool up by name when executing a tool_call.

    Tool errors never raise out of `ainvoke` here — they come back as
    `{"error": "..."}` so the LLM sees a clean message on its next turn
    instead of the graph crashing on a bad tool call.
    """
    tools: dict[str, StructuredTool] = {}
    for name, description, schema, fn in _TOOL_DEFS:

        async def _run(
            _fn: Callable[..., Awaitable[Any]] = fn,
            _schema: type[BaseModel] = schema,
            **kwargs: Any,
        ) -> dict:
            try:
                params = _schema(**kwargs)
                result = await _fn(ctx, params)
            except (ToolError, InvalidTimeWindowError) as exc:
                return {"error": str(exc)}
            return result.model_dump(mode="json")

        tools[name] = StructuredTool.from_function(
            coroutine=_run,
            name=name,
            description=description,
            args_schema=schema,
        )
    return tools
