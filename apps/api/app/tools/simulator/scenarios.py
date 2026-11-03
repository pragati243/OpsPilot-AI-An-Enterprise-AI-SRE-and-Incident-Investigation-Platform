"""Deterministic scenario catalog for the simulated production environment.

A `Service.scenario_tag` selects one of these. Each scenario carries a
symptom-level `summary` (what `get_service_health` shows) and the ground
truth used to generate consistent metrics/logs — the ground truth itself is
never returned by a tool, so an investigating agent has to read the evidence
rather than the label.
"""

from dataclasses import dataclass, field

from app.models.service import ServiceStatus
from app.tools.schemas import LogSeverity


@dataclass(frozen=True)
class MetricProfile:
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    error_rate_pct: float
    request_rate_rps: float
    cpu_pct: float
    memory_pct: float


@dataclass(frozen=True)
class LogTemplate:
    severity: LogSeverity
    message: str
    weight: int = 1


@dataclass(frozen=True)
class Scenario:
    tag: str
    status: ServiceStatus
    summary: str
    metrics: MetricProfile
    log_templates: list[LogTemplate] = field(default_factory=list)


SCENARIOS: dict[str, Scenario] = {
    "healthy": Scenario(
        tag="healthy",
        status=ServiceStatus.HEALTHY,
        summary="All systems operating normally.",
        metrics=MetricProfile(
            latency_p50_ms=45,
            latency_p95_ms=120,
            latency_p99_ms=180,
            error_rate_pct=0.1,
            request_rate_rps=250,
            cpu_pct=35,
            memory_pct=40,
        ),
        log_templates=[
            LogTemplate(LogSeverity.INFO, "Health check OK", weight=6),
            LogTemplate(LogSeverity.INFO, "Request completed in {latency}ms", weight=4),
            LogTemplate(LogSeverity.WARN, "Request latency above p95 threshold once", weight=1),
        ],
    ),
    "db_connection_pool_exhaustion": Scenario(
        tag="db_connection_pool_exhaustion",
        status=ServiceStatus.DEGRADED,
        summary=(
            "Elevated error rate and request latency over the selected window; "
            "intermittent failures reported downstream."
        ),
        metrics=MetricProfile(
            latency_p50_ms=220,
            latency_p95_ms=1800,
            latency_p99_ms=4200,
            error_rate_pct=12.5,
            request_rate_rps=180,
            cpu_pct=55,
            memory_pct=62,
        ),
        log_templates=[
            LogTemplate(
                LogSeverity.ERROR,
                "QueuePool limit of size 10 overflow 0 reached, connection timed out after 30s",
                weight=5,
            ),
            LogTemplate(
                LogSeverity.WARN, "Connection pool exhausted, queuing new request", weight=4
            ),
            LogTemplate(
                LogSeverity.ERROR,
                'psycopg2.OperationalError: FATAL: too many connections for role "app"',
                weight=2,
            ),
            LogTemplate(LogSeverity.INFO, "Health check OK", weight=2),
        ],
    ),
    "upstream_timeout": Scenario(
        tag="upstream_timeout",
        status=ServiceStatus.DEGRADED,
        summary=(
            "Increased latency correlated with calls to a dependent service; "
            "some requests are timing out."
        ),
        metrics=MetricProfile(
            latency_p50_ms=180,
            latency_p95_ms=3200,
            latency_p99_ms=6000,
            error_rate_pct=8.0,
            request_rate_rps=200,
            cpu_pct=40,
            memory_pct=45,
        ),
        log_templates=[
            LogTemplate(
                LogSeverity.ERROR,
                "Upstream request to payments-gateway timed out after 30000ms",
                weight=5,
            ),
            LogTemplate(LogSeverity.WARN, "Retrying upstream call (attempt 2/3)", weight=4),
            LogTemplate(LogSeverity.ERROR, "circuit breaker OPEN for payments-gateway", weight=2),
            LogTemplate(LogSeverity.INFO, "Health check OK", weight=2),
        ],
    ),
    "memory_leak": Scenario(
        tag="memory_leak",
        status=ServiceStatus.DOWN,
        summary="Service is failing health checks and restarting repeatedly.",
        metrics=MetricProfile(
            latency_p50_ms=500,
            latency_p95_ms=9000,
            latency_p99_ms=15000,
            error_rate_pct=45.0,
            request_rate_rps=60,
            cpu_pct=90,
            memory_pct=97,
        ),
        log_templates=[
            LogTemplate(
                LogSeverity.CRITICAL,
                "OOMKilled: container exceeded memory limit of 512Mi",
                weight=4,
            ),
            LogTemplate(
                LogSeverity.ERROR,
                "java.lang.OutOfMemoryError: GC overhead limit exceeded",
                weight=4,
            ),
            LogTemplate(LogSeverity.WARN, "Restart count: 7 in the last 15 minutes", weight=3),
        ],
    ),
    "deployment_regression": Scenario(
        tag="deployment_regression",
        status=ServiceStatus.DEGRADED,
        summary="Error rate increased shortly after the most recent deployment.",
        metrics=MetricProfile(
            latency_p50_ms=60,
            latency_p95_ms=250,
            latency_p99_ms=600,
            error_rate_pct=18.0,
            request_rate_rps=220,
            cpu_pct=38,
            memory_pct=42,
        ),
        log_templates=[
            LogTemplate(
                LogSeverity.ERROR,
                "panic: runtime error: invalid memory address or nil pointer dereference",
                weight=5,
            ),
            LogTemplate(
                LogSeverity.ERROR, "goroutine 42 [running]: handler.ProcessOrder(...)", weight=3
            ),
            LogTemplate(
                LogSeverity.INFO, "Deployment v2.14.3 rolled out to 100% of traffic", weight=1
            ),
            LogTemplate(LogSeverity.INFO, "Health check OK", weight=2),
        ],
    ),
}


def get_scenario(tag: str) -> Scenario:
    return SCENARIOS.get(tag, SCENARIOS["healthy"])
