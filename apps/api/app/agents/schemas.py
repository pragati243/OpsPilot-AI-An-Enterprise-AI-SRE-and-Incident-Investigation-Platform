from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

READ_ONLY_TOOL_NAMES = (
    "get_service_health",
    "query_logs",
    "get_service_metrics",
    "search_runbooks",
    "search_past_incidents",
)


class PlannedStep(BaseModel):
    tool: Literal[
        "get_service_health",
        "query_logs",
        "get_service_metrics",
        "search_runbooks",
        "search_past_incidents",
    ]
    reason: str = Field(description="Why this tool call is relevant to the incident")


class InvestigationPlan(BaseModel):
    hypothesis: str = Field(description="Initial, unverified hypothesis about the root cause")
    steps: list[PlannedStep] = Field(
        max_length=6, description="Bounded, ordered list of diagnostic tool calls to try first"
    )


class EvidenceItem(BaseModel):
    tool: str
    input: dict
    output: dict
    timestamp: datetime
    error: str | None = None


class Assessment(BaseModel):
    leading_hypothesis: str
    supporting_evidence: list[str] = Field(
        default_factory=list, description="Short pointers into the gathered evidence"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    missing_evidence: list[str] = Field(
        default_factory=list, description="What would still need to be checked"
    )
    ready_to_report: bool = Field(
        description="True once there is enough evidence to write a report, even an uncertain one"
    )


class RecommendedAction(BaseModel):
    action_type: str
    rationale: str


class InvestigationReport(BaseModel):
    diagnosis: str = Field(
        description="State the evidence-backed diagnosis, or state plainly that the "
        "evidence was insufficient to determine a root cause"
    )
    evidence_summary: str
    resolution: str | None = Field(
        default=None,
        description="Fill in only if the issue is already resolved without further action "
        "(e.g. transient and recovered). Leave null when fixing it requires one of "
        "recommended_actions — those need approval before they count as a resolution.",
    )
    citations: list[str] = Field(
        default_factory=list, description="Tool names, document ids, or past incident ids relied on"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    outcome: Literal["resolved", "unresolved", "escalated"]
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    uncertainty_note: str | None = Field(
        default=None, description="Set when evidence was insufficient for a confident diagnosis"
    )
