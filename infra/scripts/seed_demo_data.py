"""Seed one demo tenant with services, runbooks, and incidents so the API
(and later, the dashboard) have something real to show without hand-running
the test suite. Idempotent: checks for existing rows by natural key before
creating anything, so re-running it is safe.

Usage: uv run python infra/scripts/seed_demo_data.py
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.core.security import hash_password  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.document import DocumentSourceType  # noqa: E402
from app.models.episode import EpisodeOutcome  # noqa: E402
from app.models.incident import IncidentSeverity, IncidentStatus  # noqa: E402
from app.models.service import ServiceStatus  # noqa: E402
from app.models.user import UserRole  # noqa: E402
from app.repositories.document_repository import DocumentRepository  # noqa: E402
from app.repositories.episode_repository import EpisodeRepository  # noqa: E402
from app.repositories.incident_repository import IncidentRepository  # noqa: E402
from app.repositories.service_repository import ServiceRepository  # noqa: E402
from app.repositories.tenant_repository import TenantRepository  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402

DEMO_TENANT_SLUG = "demo-corp"
DEMO_TENANT_NAME = "Demo Corp"
DEMO_ADMIN_EMAIL = "admin@demo-corp.io"
DEMO_ADMIN_PASSWORD = "demo-password-change-me"

SERVICES = [
    # name, environment, description, owner_team, status, scenario_tag
    (
        "checkout-service",
        "production",
        "Handles cart checkout and payment capture",
        "payments-team",
        ServiceStatus.DEGRADED,
        "db_connection_pool_exhaustion",
    ),
    (
        "api-gateway",
        "production",
        "Edge routing for all public APIs",
        "platform-team",
        ServiceStatus.HEALTHY,
        "healthy",
    ),
    (
        "notification-service",
        "production",
        "Sends transactional email and SMS",
        "growth-team",
        ServiceStatus.HEALTHY,
        "healthy",
    ),
    (
        "payments-worker",
        "production",
        "Async settlement jobs against the payments gateway",
        "payments-team",
        ServiceStatus.DEGRADED,
        "upstream_timeout",
    ),
    (
        "inventory-service",
        "production",
        "Stock levels and reservation",
        "catalog-team",
        ServiceStatus.DOWN,
        "memory_leak",
    ),
    (
        "search-service",
        "production",
        "Product search and ranking",
        "catalog-team",
        ServiceStatus.DEGRADED,
        "deployment_regression",
    ),
]

RUNBOOKS = [
    (
        "Diagnosing database connection pool exhaustion",
        [],
        """Symptoms: elevated p99 latency, error rate above 5%, logs showing
"QueuePool limit ... overflow ... connection timed out". Steps: 1) Check
get_service_metrics for latency and error rate. 2) query_logs for
QueuePool/OperationalError lines. 3) Verify no long-running transaction is
holding connections. 4) If the pool is simply undersized for current
traffic, propose_remediation with action_type=restart_service to clear
stuck connections as a stopgap, and file a follow-up to raise pool size.""",
    ),
    (
        "Runbook: upstream timeout to a dependent service",
        [],
        """Symptoms: latency spikes correlated with calls to an external
dependency; logs show "timed out" and "circuit breaker OPEN". Steps: 1)
Confirm via get_service_metrics that latency (not error rate) is the primary
signal. 2) query_logs filtered to ERROR for the specific upstream name. 3)
Check the upstream's own status page if available. 4) If the upstream is
degraded, there is often nothing to fix locally except backoff/retry
tuning — avoid restarting the service, it will not fix an external outage.""",
    ),
    (
        "Restricted: database failover procedure",
        ["admin", "approver"],
        """This runbook is restricted to admins/approvers because failover
is a high-risk, hard-to-reverse action. Steps: 1) Confirm the primary
database is actually unreachable, not just slow, via get_service_metrics
across multiple windows. 2) Page the on-call DBA before proposing failover.
3) Only propose_remediation with action_type=failover_database after
explicit sign-off; this always requires approval regardless of urgency.""",
    ),
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        tenants = TenantRepository(db)
        users = UserRepository(db)

        tenant = await tenants.get_by_slug(DEMO_TENANT_SLUG)
        if tenant is None:
            tenant = await tenants.create(name=DEMO_TENANT_NAME, slug=DEMO_TENANT_SLUG)
            print(f"created tenant {tenant.slug} ({tenant.id})")
        else:
            print(f"tenant {tenant.slug} already exists ({tenant.id})")

        admin = await users.get_by_email(DEMO_ADMIN_EMAIL)
        if admin is None:
            admin = await users.create(
                tenant_id=tenant.id,
                email=DEMO_ADMIN_EMAIL,
                hashed_password=hash_password(DEMO_ADMIN_PASSWORD),
                full_name="Demo Admin",
                role=UserRole.ADMIN,
            )
            print(f"created admin user {admin.email}")
        else:
            print(f"admin user {admin.email} already exists")

        service_repo = ServiceRepository(db)
        services_by_name = {}
        for name, environment, description, owner_team, status, scenario_tag in SERVICES:
            service = await service_repo.get_by_name(
                tenant_id=tenant.id, name=name, environment=environment
            )
            if service is None:
                service = await service_repo.create(
                    tenant_id=tenant.id,
                    name=name,
                    environment=environment,
                    description=description,
                    owner_team=owner_team,
                    status=status,
                    scenario_tag=scenario_tag,
                )
                print(f"created service {name} ({status.value}, {scenario_tag})")
            services_by_name[name] = service

        document_repo = DocumentRepository(db)
        for title, access_scope, content in RUNBOOKS:
            existing = await document_repo.search(
                tenant_id=tenant.id,
                query=title,
                source_type=DocumentSourceType.RUNBOOK,
                allowed_scopes={"public", "admin", "sre", "approver", "viewer"},
            )
            if any(doc.title == title for doc in existing):
                print(f"runbook {title!r} already exists")
                continue
            await document_repo.create(
                tenant_id=tenant.id,
                title=title,
                source_type=DocumentSourceType.RUNBOOK,
                content=content,
                access_scope=access_scope,
                created_by=admin.id,
            )
            print(f"created runbook {title!r}")

        incident_repo = IncidentRepository(db)
        episode_repo = EpisodeRepository(db)

        past_title = "Checkout latency spike — resolved"
        existing_past = await incident_repo.search(
            tenant_id=tenant.id, query=past_title, service="checkout-service", limit=1
        )
        if not existing_past:
            past_incident = await incident_repo.create(
                tenant_id=tenant.id,
                title=past_title,
                service="checkout-service",
                environment="production",
                severity=IncidentSeverity.SEV2,
                status=IncidentStatus.RESOLVED,
                created_by=admin.id,
            )
            resolved_at = datetime.now(UTC) - timedelta(days=10)
            await incident_repo.update_status(
                incident=past_incident, status=IncidentStatus.RESOLVED, resolved_at=resolved_at
            )
            await episode_repo.create(
                tenant_id=tenant.id,
                incident_id=past_incident.id,
                evidence={
                    "metrics": {"latency_p99_ms": 4100, "error_rate_pct": 11.8},
                    "logs": ["QueuePool limit of size 10 overflow 0 reached"],
                },
                diagnosis=(
                    "Database connection pool exhausted due to a slow query holding "
                    "connections under peak load."
                ),
                resolution=(
                    "Restarted checkout-service to clear stuck connections and raised "
                    "the pool size from 10 to 25."
                ),
                outcome=EpisodeOutcome.RESOLVED,
                confidence=0.92,
            )
            print(f"created resolved past incident {past_title!r} with episode")
        else:
            print(f"past incident {past_title!r} already exists")

        active_title = "Checkout error rate elevated"
        existing_active = await incident_repo.search(
            tenant_id=tenant.id, query=active_title, service="checkout-service", limit=1
        )
        if not existing_active:
            await incident_repo.create(
                tenant_id=tenant.id,
                title=active_title,
                service="checkout-service",
                environment="production",
                severity=IncidentSeverity.SEV2,
                status=IncidentStatus.INVESTIGATING,
                created_by=admin.id,
            )
            print(f"created active incident {active_title!r} (mirrors the resolved one)")
        else:
            print(f"active incident {active_title!r} already exists")

        inventory_title = "Inventory service down — OOM restarts"
        existing_inventory = await incident_repo.search(
            tenant_id=tenant.id, query=inventory_title, service="inventory-service", limit=1
        )
        if not existing_inventory:
            await incident_repo.create(
                tenant_id=tenant.id,
                title=inventory_title,
                service="inventory-service",
                environment="production",
                severity=IncidentSeverity.SEV1,
                status=IncidentStatus.OPEN,
                created_by=admin.id,
            )
            print(f"created active incident {inventory_title!r}")
        else:
            print(f"active incident {inventory_title!r} already exists")

        await db.commit()
        print(
            f"\nDone. Login with {DEMO_ADMIN_EMAIL} / {DEMO_ADMIN_PASSWORD} "
            f"(tenant {DEMO_TENANT_SLUG})."
        )


if __name__ == "__main__":
    asyncio.run(main())
