import os
import sys
import uuid
from pathlib import Path

# apps/mcp-server itself (parent of this tests/ dir) has to be on sys.path
# for `import server`/`import bootstrap` below and in test_mcp_server.py —
# pytest's rootless collection only adds a test file's own directory, not
# its parent. `pythonpath` in pyproject.toml covers apps/api the same way
# for apps/api/tests, but doesn't reach a sibling app, so this file does it
# for itself rather than depending on that setting also listing this path.
_MCP_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_MCP_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_SERVER_ROOT))

# Same env isolation as apps/api/tests/conftest.py, duplicated rather than
# imported: this test runs in the same `uv run pytest` process as that
# suite (both are in pyproject.toml's testpaths), so whichever conftest's
# module-level code runs first during collection wins — they have to agree,
# not depend on one one importing the other.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://opspilot:opspilot@localhost:5545/opspilot_test",
)
os.environ.setdefault("ENV", "test")
os.environ.setdefault(
    "REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://localhost:6399/15")
)
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-at-least-32-bytes-long")
os.environ.setdefault("APP_SECRET_KEY", "test-only-secret-key-at-least-32-bytes-long-too")
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""

import bootstrap  # noqa: E402,F401  — inserts apps/api onto sys.path
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.document import Document, DocumentSourceType  # noqa: E402
from app.models.service import Service, ServiceStatus  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database():
    """Self-sufficient schema setup, so `uv run pytest apps/mcp-server/tests`
    works on its own. Duplicates apps/api/tests/conftest.py's fixture of the
    same name rather than importing it (sibling conftests can't share
    fixtures); both `CREATE EXTENSION IF NOT EXISTS` and `create_all`/
    `drop_all` are idempotent, so no conflict running alongside that suite
    in the same `uv run pytest` session.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def mcp_fixture_tenant():
    """Unlike apps/api/tests' `db_session` fixture, this *commits* its rows:
    the MCP server's `authenticated_tool_context` opens its own independent
    `AsyncSessionLocal()` (simulating a separate client process), which
    can't see another connection's uncommitted/rolled-back transaction.
    Cleanup is one DELETE on the tenant — every row created below cascades
    from `tenants.id` (see each model's `ForeignKey(..., ondelete="CASCADE")`).
    """
    async with AsyncSessionLocal() as session:
        slug = f"mcp-test-{uuid.uuid4().hex[:8]}"
        tenant = Tenant(name=slug, slug=slug)
        session.add(tenant)
        await session.flush()

        user = User(
            tenant_id=tenant.id,
            email=f"user-{uuid.uuid4().hex[:8]}@example.io",
            hashed_password=hash_password("not-used-in-this-test"),
            full_name="MCP Test User",
            role=UserRole.SRE,
        )
        session.add(user)

        service = Service(
            tenant_id=tenant.id,
            name="checkout-service",
            environment="production",
            scenario_tag="healthy",
            status=ServiceStatus.HEALTHY,
        )
        session.add(service)

        document = Document(
            tenant_id=tenant.id,
            title="Checkout latency runbook",
            source_type=DocumentSourceType.RUNBOOK,
            content=(
                "If checkout-service latency spikes, first check the database "
                "connection pool utilization before scaling replicas."
            ),
            access_scope=[],
        )
        session.add(document)

        await session.commit()
        await session.refresh(user)
        await session.refresh(service)
        await session.refresh(document)

        token = create_access_token(
            subject=user.id, tenant_id=tenant.id, role=user.role.value
        )

        try:
            yield {
                "tenant": tenant,
                "user": user,
                "service": service,
                "document": document,
                "token": token,
            }
        finally:
            await session.delete(tenant)
            await session.commit()
