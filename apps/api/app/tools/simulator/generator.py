import hashlib
import random
import uuid
from datetime import datetime, timedelta

from app.models.service import Service
from app.tools.schemas import SEVERITY_ORDER, LogEntry, LogSeverity, MetricsSnapshot
from app.tools.simulator.scenarios import get_scenario

# Metrics/logs are bucketed by hour so repeated tool calls within one
# investigation see consistent evidence instead of re-randomizing on every
# call, while still varying hour to hour.
_BUCKET_SECONDS = 3600
_MAX_LOG_LINES = 500
_SECONDS_PER_LOG_LINE = 20


def _seed_for(tenant_id: uuid.UUID, service_id: uuid.UUID, bucket: int) -> int:
    digest = hashlib.sha256(f"{tenant_id}:{service_id}:{bucket}".encode()).hexdigest()
    return int(digest[:16], 16)


def _bucket(now: datetime) -> int:
    return int(now.timestamp() // _BUCKET_SECONDS)


def generate_metrics(
    service: Service, window: timedelta, now: datetime, *, time_window_label: str
) -> MetricsSnapshot:
    scenario = get_scenario(service.scenario_tag)
    profile = scenario.metrics
    rng = random.Random(_seed_for(service.tenant_id, service.id, _bucket(now)))

    def jitter(value: float, pct: float = 0.08) -> float:
        return round(value * (1 + rng.uniform(-pct, pct)), 2)

    sample_count = max(1, int(profile.request_rate_rps * window.total_seconds()))

    return MetricsSnapshot(
        service=service.name,
        time_window=time_window_label,
        latency_p50_ms=jitter(profile.latency_p50_ms),
        latency_p95_ms=jitter(profile.latency_p95_ms),
        latency_p99_ms=jitter(profile.latency_p99_ms),
        error_rate_pct=round(max(0.0, jitter(profile.error_rate_pct)), 2),
        request_rate_rps=jitter(profile.request_rate_rps),
        cpu_pct=round(min(100.0, max(0.0, jitter(profile.cpu_pct))), 2),
        memory_pct=round(min(100.0, max(0.0, jitter(profile.memory_pct))), 2),
        sample_count=sample_count,
    )


def generate_logs(
    service: Service,
    window: timedelta,
    now: datetime,
    *,
    min_severity: LogSeverity,
    limit: int,
    time_window_label: str,
) -> tuple[list[LogEntry], int, bool]:
    """Returns (entries capped at `limit`, total_matched before the cap, truncated)."""
    scenario = get_scenario(service.scenario_tag)
    rng = random.Random(_seed_for(service.tenant_id, service.id, _bucket(now)) ^ 0xA5A5)

    window_seconds = window.total_seconds()
    line_count = min(_MAX_LOG_LINES, max(1, int(window_seconds / _SECONDS_PER_LOG_LINE)))

    templates = scenario.log_templates
    weights = [t.weight for t in templates]

    entries: list[LogEntry] = []
    for _ in range(line_count):
        template = rng.choices(templates, weights=weights, k=1)[0]
        offset = rng.uniform(0, window_seconds)
        entries.append(
            LogEntry(
                timestamp=now - timedelta(seconds=offset),
                severity=template.severity,
                message=template.message,
            )
        )

    entries.sort(key=lambda e: e.timestamp, reverse=True)

    min_rank = SEVERITY_ORDER[min_severity]
    matched = [e for e in entries if SEVERITY_ORDER[e.severity] >= min_rank]

    truncated = len(matched) > limit
    return matched[:limit], len(matched), truncated
