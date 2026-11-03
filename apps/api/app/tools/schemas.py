import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.episode import EpisodeOutcome
from app.models.remediation import RemediationRiskLevel, RemediationStatus
from app.models.service import ServiceStatus


class LogSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


SEVERITY_ORDER: dict[LogSeverity, int] = {
    LogSeverity.DEBUG: 0,
    LogSeverity.INFO: 1,
    LogSeverity.WARN: 2,
    LogSeverity.ERROR: 3,
    LogSeverity.CRITICAL: 4,
}


# --- get_service_health ---


class GetServiceHealthInput(BaseModel):
    service: str
    environment: str = "production"


class ServiceHealthResult(BaseModel):
    service: str
    environment: str
    status: ServiceStatus
    summary: str


# --- query_logs ---


class QueryLogsInput(BaseModel):
    service: str
    environment: str = "production"
    time_window: str = "15m"
    min_severity: LogSeverity = LogSeverity.WARN
    limit: int = Field(default=50, ge=1, le=500)


class LogEntry(BaseModel):
    timestamp: datetime
    severity: LogSeverity
    message: str


class QueryLogsResult(BaseModel):
    service: str
    time_window: str
    entries: list[LogEntry]
    total_matched: int
    truncated: bool


# --- get_service_metrics ---


class GetServiceMetricsInput(BaseModel):
    service: str
    environment: str = "production"
    time_window: str = "15m"


class MetricsSnapshot(BaseModel):
    service: str
    time_window: str
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    error_rate_pct: float
    request_rate_rps: float
    cpu_pct: float
    memory_pct: float
    sample_count: int


# --- search_runbooks ---


class SearchRunbooksInput(BaseModel):
    query: str = Field(min_length=1)
    service: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


class RunbookMatch(BaseModel):
    document_id: uuid.UUID
    title: str
    snippet: str
    score: float


class SearchRunbooksResult(BaseModel):
    query: str
    matches: list[RunbookMatch]


# --- search_past_incidents ---


class SearchPastIncidentsInput(BaseModel):
    query: str = Field(min_length=1)
    service: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


class PastIncidentMatch(BaseModel):
    incident_id: uuid.UUID
    title: str
    service: str
    severity: str
    status: str
    diagnosis: str | None
    resolution: str | None
    outcome: EpisodeOutcome | None
    created_at: datetime
    score: float


class SearchPastIncidentsResult(BaseModel):
    query: str
    matches: list[PastIncidentMatch]


# --- create_incident_report ---


class CreateIncidentReportInput(BaseModel):
    incident_id: uuid.UUID
    diagnosis: str = Field(min_length=1)
    evidence: dict = Field(default_factory=dict)
    resolution: str | None = None
    outcome: EpisodeOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[str] = Field(default_factory=list)


class CreateIncidentReportResult(BaseModel):
    episode_id: uuid.UUID
    incident_id: uuid.UUID
    incident_status: str


# --- propose_remediation ---


class ProposeRemediationInput(BaseModel):
    incident_id: uuid.UUID
    action_type: str
    action_params: dict = Field(default_factory=dict)
    rationale: str = Field(min_length=1)


class ProposeRemediationResult(BaseModel):
    proposal_id: uuid.UUID
    incident_id: uuid.UUID
    action_type: str
    risk_level: RemediationRiskLevel
    status: RemediationStatus
    requires_approval: bool
