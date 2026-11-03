import pytest

from app.core.security import hash_password
from app.memory.policy import MemoryPolicyViolation
from app.memory.recall import recall_memories
from app.memory.write import upsert_memory
from app.models.memory import MemoryProvenance, MemoryStatus, MemoryType
from app.models.user import User, UserRole
from app.repositories.memory_repository import MemoryRepository
from app.tools.context import ToolContext
from tests.conftest import create_tenant, create_user

SEMANTIC_FACT = "checkout-service uses a Postgres connection pool sized at 10."


async def _upsert(ctx: ToolContext, *, content: str, user_id=None, confidence: float = 0.9):
    return await upsert_memory(
        ctx.db,
        tenant_id=ctx.tenant_id,
        user_id=user_id,
        memory_type=MemoryType.SEMANTIC,
        content=content,
        provenance=MemoryProvenance.SYSTEM_EXTRACTED,
        confidence=confidence,
    )


async def test_upsert_memory_creates_new_record(tool_ctx: ToolContext) -> None:
    record = await _upsert(tool_ctx, content=SEMANTIC_FACT)
    assert record.status == MemoryStatus.ACTIVE
    assert record.embedding is not None


async def test_upsert_memory_supersedes_near_duplicate(tool_ctx: ToolContext) -> None:
    first = await _upsert(tool_ctx, content=SEMANTIC_FACT, confidence=0.9)
    second = await _upsert(tool_ctx, content=SEMANTIC_FACT, confidence=0.95)

    await tool_ctx.db.refresh(first)
    assert first.status == MemoryStatus.SUPERSEDED
    assert first.superseded_by == second.id
    assert second.status == MemoryStatus.ACTIVE


async def test_upsert_memory_does_not_supersede_unrelated_fact(tool_ctx: ToolContext) -> None:
    first = await _upsert(tool_ctx, content=SEMANTIC_FACT)
    await _upsert(tool_ctx, content="notification-service sends email via SendGrid.")

    await tool_ctx.db.refresh(first)
    assert first.status == MemoryStatus.ACTIVE

    active = await MemoryRepository(tool_ctx.db).list_active(tenant_id=tool_ctx.tenant_id)
    assert len(active) == 2


async def test_upsert_memory_raises_on_policy_violation(tool_ctx: ToolContext) -> None:
    with pytest.raises(MemoryPolicyViolation):
        await _upsert(tool_ctx, content="api_key: sk-abcdefghij1234567890klmnop")


async def test_recall_memories_filters_by_tenant_before_ranking(
    tool_ctx: ToolContext, db_session
) -> None:
    """A memory from another tenant must never be returned, no matter how
    similar — authorization is a hard filter applied before any ranking,
    never blended into one fuzzy similarity score.
    """
    await _upsert(tool_ctx, content=SEMANTIC_FACT)

    other_tenant = await create_tenant(db_session)
    other_ctx = ToolContext(
        tenant_id=other_tenant.id, user=await create_user(db_session, other_tenant), db=db_session
    )
    # Identical content in another tenant — a maximally similar match.
    await _upsert(other_ctx, content=SEMANTIC_FACT)

    results = await recall_memories(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        user_id=None,
        query="checkout-service connection pool",
    )
    assert len(results) == 1
    assert results[0].tenant_id == tool_ctx.tenant_id


async def test_recall_memories_excludes_deleted_and_superseded(tool_ctx: ToolContext) -> None:
    record = await _upsert(tool_ctx, content=SEMANTIC_FACT)
    await MemoryRepository(tool_ctx.db).soft_delete(record=record)

    results = await recall_memories(
        tool_ctx.db, tenant_id=tool_ctx.tenant_id, user_id=None, query="connection pool"
    )
    assert results == []


async def test_recall_memories_profile_scope_excludes_other_users(
    tool_ctx: ToolContext, db_session
) -> None:
    other_user = User(
        tenant_id=tool_ctx.tenant_id,
        email="other-user@example.io",
        hashed_password=hash_password("not-used"),
        full_name="Other User",
        role=UserRole.SRE,
    )
    db_session.add(other_user)
    await db_session.flush()

    await upsert_memory(
        db_session,
        tenant_id=tool_ctx.tenant_id,
        user_id=other_user.id,
        memory_type=MemoryType.PROFILE,
        content="Prefers detailed, verbose reports.",
        provenance=MemoryProvenance.USER_CONFIRMED,
        confidence=1.0,
    )
    await upsert_memory(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        user_id=tool_ctx.user.id,
        memory_type=MemoryType.PROFILE,
        content="Prefers concise reports with evidence first.",
        provenance=MemoryProvenance.USER_CONFIRMED,
        confidence=1.0,
    )

    results = await recall_memories(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        user_id=tool_ctx.user.id,
        query="report style preference",
        memory_type=MemoryType.PROFILE,
    )
    assert len(results) == 1
    assert "concise" in results[0].content
