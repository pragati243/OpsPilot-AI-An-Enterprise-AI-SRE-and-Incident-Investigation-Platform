import operator
import uuid
from datetime import datetime
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from app.agents.schemas import Assessment, EvidenceItem, InvestigationPlan, InvestigationReport


class InvestigationState(TypedDict, total=False):
    # intake
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    incident_id: uuid.UUID
    incident_title: str
    service: str
    environment: str
    authorized: bool
    error: str | None

    # conversation / tool-calling transcript fed to the LLM
    messages: Annotated[list[AnyMessage], add_messages]

    # plan
    plan: InvestigationPlan | None

    # gather
    evidence: Annotated[list[EvidenceItem], operator.add]
    tool_call_count: int

    # assess
    assessment: Assessment | None
    gather_iteration: int

    # bounds — see app/agents/graph.py for the actual defaults
    max_tool_calls: int
    max_gather_iterations: int
    deadline: datetime

    # report
    report: InvestigationReport | None
