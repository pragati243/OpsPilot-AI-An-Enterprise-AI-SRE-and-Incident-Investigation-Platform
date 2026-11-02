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
os.environ.setdefault("REDIS_URL", "redis://localhost:6399/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-at-least-32-bytes-long")
os.environ.setdefault("APP_SECRET_KEY", "test-only-secret-key-at-least-32-bytes-long-too")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.base import Base
from app.db.session import engine
from app.main import app


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database():
    """Create the full schema once per test run and drop it afterwards.
    Keeps the test suite self-sufficient without requiring `alembic upgrade
    head` to have been run against the test database first.
    """
    async with engine.begin() as conn:
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
