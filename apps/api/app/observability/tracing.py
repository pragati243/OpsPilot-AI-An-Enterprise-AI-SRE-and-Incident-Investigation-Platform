import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import propagate_attributes

from app.observability.client import get_langfuse_client

WORKFLOW_VERSION = "v1"


@contextmanager
def investigation_trace(
    *, tenant_id: uuid.UUID, user_id: uuid.UUID, incident_id: uuid.UUID
) -> Iterator[Any]:
    """Root span for one investigation run. Every node/generation/tool/
    retriever span created anywhere during the run (see graph.py and the
    node/tool/retrieval modules) becomes a child of this one, since
    LangGraph's async execution stays on the same OS thread the context
    vars live on.

    `propagate_attributes` has to be entered *inside* the root span, not
    wrapping its creation — Langfuse's own docs call this out, and it's
    also what worked empirically against a real project (wrapping it the
    other way around logs a spurious "no active span" warning and the
    attributes don't consistently attach).
    """
    client = get_langfuse_client()
    with client.start_as_current_observation(
        name="investigate_incident",
        as_type="span",
        input={"incident_id": str(incident_id)},
    ) as root_span:
        with propagate_attributes(
            user_id=str(user_id),
            session_id=str(incident_id),
            metadata={"tenant_id": str(tenant_id)},
            version=WORKFLOW_VERSION,
            tags=["opspilot-investigation"],
            trace_name="investigate_incident",
        ):
            yield root_span
