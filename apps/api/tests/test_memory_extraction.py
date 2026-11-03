import uuid

from app.memory.extraction import extract_and_store_memories
from app.memory.schemas import ExtractedMemories, MemoryCandidate
from app.models.episode import EpisodeOutcome
from app.models.incident import IncidentSeverity, IncidentStatus
from app.models.memory import MemoryStatus
from app.repositories.episode_repository import EpisodeRepository
from app.repositories.incident_repository import IncidentRepository
from app.repositories.memory_repository import MemoryRepository
from app.tools.context import ToolContext
from tests.fakes import FakeAgentLLM


def _llm_with(*candidates: MemoryCandidate) -> FakeAgentLLM:
    return FakeAgentLLM(
        structured_responses={ExtractedMemories: [ExtractedMemories(candidates=list(candidates))]}
    )


async def _seed_episode(ctx: ToolContext) -> uuid.UUID:
    """source_episode_id is a real FK — extraction always runs after
    create_incident_report has already persisted the episode it learns
    from, so tests need one too, not just a random UUID.
    """
    incident = await IncidentRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        title="Checkout error rate elevated",
        service="checkout-service",
        environment="production",
        severity=IncidentSeverity.SEV2,
        status=IncidentStatus.RESOLVED,
        created_by=ctx.user.id,
    )
    episode = await EpisodeRepository(ctx.db).create(
        tenant_id=ctx.tenant_id,
        incident_id=incident.id,
        evidence={},
        diagnosis="Connection pool exhausted.",
        resolution="Restarted the service.",
        outcome=EpisodeOutcome.RESOLVED,
        confidence=0.9,
    )
    return episode.id


async def test_extraction_stores_valid_candidates(tool_ctx: ToolContext) -> None:
    llm = _llm_with(
        MemoryCandidate(
            memory_type="semantic",
            content="checkout-service uses a Postgres connection pool sized at 10.",
            confidence=0.9,
        )
    )
    stored = await extract_and_store_memories(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        source_episode_id=await _seed_episode(tool_ctx),
        llm=llm,
        incident_title="Checkout error rate elevated",
        service="checkout-service",
        diagnosis="Connection pool exhausted.",
        evidence_summary="n/a",
    )
    assert len(stored) == 1
    assert stored[0].status == MemoryStatus.ACTIVE


async def test_extraction_handles_empty_candidates(tool_ctx: ToolContext) -> None:
    llm = _llm_with()
    stored = await extract_and_store_memories(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        source_episode_id=await _seed_episode(tool_ctx),
        llm=llm,
        incident_title="n/a",
        service="checkout-service",
        diagnosis="n/a",
        evidence_summary="n/a",
    )
    assert stored == []


async def test_extraction_skips_policy_violating_candidate_without_crashing(
    tool_ctx: ToolContext,
) -> None:
    llm = _llm_with(
        MemoryCandidate(
            memory_type="semantic",
            content="the api_key: sk-abcdefghij1234567890klmnop was used to fix this",
            confidence=0.9,
        ),
        MemoryCandidate(
            memory_type="procedural",
            content="Restarting checkout-service clears stuck DB connections.",
            confidence=0.8,
        ),
    )
    stored = await extract_and_store_memories(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        source_episode_id=await _seed_episode(tool_ctx),
        llm=llm,
        incident_title="n/a",
        service="checkout-service",
        diagnosis="n/a",
        evidence_summary="n/a",
    )
    # Only the second, policy-clean candidate should have been stored.
    assert len(stored) == 1
    assert "Restarting checkout-service" in stored[0].content


async def test_extraction_supersedes_near_duplicate_across_episodes(
    tool_ctx: ToolContext,
) -> None:
    fact = "checkout-service uses a Postgres connection pool sized at 10."

    first = await extract_and_store_memories(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        source_episode_id=await _seed_episode(tool_ctx),
        llm=_llm_with(MemoryCandidate(memory_type="semantic", content=fact, confidence=0.9)),
        incident_title="n/a",
        service="checkout-service",
        diagnosis="n/a",
        evidence_summary="n/a",
    )
    second = await extract_and_store_memories(
        tool_ctx.db,
        tenant_id=tool_ctx.tenant_id,
        source_episode_id=await _seed_episode(tool_ctx),
        llm=_llm_with(MemoryCandidate(memory_type="semantic", content=fact, confidence=0.95)),
        incident_title="n/a",
        service="checkout-service",
        diagnosis="n/a",
        evidence_summary="n/a",
    )

    await tool_ctx.db.refresh(first[0])
    assert first[0].status == MemoryStatus.SUPERSEDED
    assert second[0].status == MemoryStatus.ACTIVE

    active = await MemoryRepository(tool_ctx.db).list_active(tenant_id=tool_ctx.tenant_id)
    assert len(active) == 1
