import os

# Force tests onto the ephemeral test database regardless of whatever
# DATABASE_URL is in .env, so a misconfigured environment can never point
# the test suite at real data. TEST_DATABASE_URL lets CI (and any machine
# without this repo's local port remapping) point at its own instance; it
# defaults to the docker-compose `postgres-test` service (--profile test).
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://opspilot:opspilot@localhost:5545/opspilot_test",
)
os.environ.setdefault("ENV", "test")
# A dedicated logical DB (15), not dev's /0 — rate-limit counters live in
# Redis, not inside the per-test Postgres transaction rollback, so without
# this every test would share one counter and later tests would start
# seeing 429s from earlier tests' calls to the same endpoint.
os.environ.setdefault(
    "REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://localhost:6399/15")
)
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-at-least-32-bytes-long")
os.environ.setdefault("APP_SECRET_KEY", "test-only-secret-key-at-least-32-bytes-long-too")
# Tests must never ship real spans to Langfuse Cloud. pydantic-settings
# reads .env directly (env_file=".env"), so popping these from os.environ
# would NOT override a real .env value — pydantic-settings' precedence is
# process env > .env file, so setting them to "" here is what actually
# wins and disables the client (see get_langfuse_client's `configured`
# check, which treats an empty string as "not configured").
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
# Same reasoning, same mechanism, for Groq: tests must never make a real
# LLM call even if a real key later lands in .env. Tests that need the
# agent to do anything override `get_agent_llm` with a FakeAgentLLM
# anyway — this only matters for the one test that deliberately exercises
# the *real* get_agent_llm dependency's "not configured" fallback.
os.environ["GROQ_API_KEY"] = ""

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import engine
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.tools.context import ToolContext


@pytest_asyncio.fixture(autouse=True)
async def _flush_test_redis():
    """Redis state (rate-limit counters today) isn't covered by the
    per-test Postgres transaction rollback, so it gets its own cleanup:
    flush the dedicated test DB (REDIS_URL above points at /15) before
    every test, not just once per session, so tests can't see each
    other's counters regardless of run order.
    """
    from app.core.redis_client import get_redis_client

    await get_redis_client().flushdb()
    yield


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database():
    """Create the full schema once per test run and drop it afterwards.
    Keeps the test suite self-sufficient without requiring `alembic upgrade
    head` to have been run against the test database first.

    The `vector` extension has to exist before create_all(), since
    Document.embedding's column type depends on it — `CREATE EXTENSION` is
    per-database, so the ephemeral test Postgres needs it too, not just dev.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    """One connection-level transaction per test, with the app session
    joined via a SAVEPOINT so that `session.commit()` calls in service code
    don't actually persist anything past the test (SQLAlchemy 2.0's
    documented pattern for joining a Session into an external transaction).
    """
    async with engine.connect() as connection:
        await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await connection.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def create_tenant(db_session: AsyncSession, *, slug: str | None = None) -> Tenant:
    """Helper (not a fixture) so tool/guardrail tests can create more than
    one tenant per test, e.g. for cross-tenant isolation checks.
    """
    slug = slug or f"tenant-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(name=slug, slug=slug)
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def create_user(
    db_session: AsyncSession, tenant: Tenant, *, role: UserRole = UserRole.SRE
) -> User:
    user = User(
        tenant_id=tenant.id,
        email=f"user-{uuid.uuid4().hex[:8]}@example.io",
        hashed_password=hash_password("not-used-in-tool-tests"),
        full_name="Test User",
        role=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def tool_ctx(db_session: AsyncSession) -> ToolContext:
    """A fresh tenant + SRE user wrapped in a ToolContext, for tests that
    call tool functions directly rather than through the HTTP API.
    """
    tenant = await create_tenant(db_session)
    user = await create_user(db_session, tenant)
    return ToolContext(tenant_id=tenant.id, user=user, db=db_session)
