import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import AgentLLM
from app.core.logging import get_logger
from app.memory.policy import MemoryPolicyViolation
from app.memory.prompts import EXTRACTION_SYSTEM_PROMPT
from app.memory.schemas import ExtractedMemories
from app.memory.write import upsert_memory
from app.models.memory import MemoryProvenance, MemoryRecord, MemoryType

logger = get_logger(__name__)


async def extract_and_store_memories(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source_episode_id: uuid.UUID,
    llm: AgentLLM,
    incident_title: str,
    service: str,
    diagnosis: str,
    evidence_summary: str,
) -> list[MemoryRecord]:
    """Candidate extraction from a verified, already-persisted report.
    Every candidate still goes through the deterministic policy gate and
    near-duplicate supersession (via `upsert_memory`) before it's stored —
    the LLM proposes, the policy layer disposes.
    """
    prompt = (
        f"Incident: {incident_title}\n"
        f"Service: {service}\n"
        f"Diagnosis: {diagnosis}\n"
        f"Evidence summary: {evidence_summary}"
    )
    messages = [SystemMessage(content=EXTRACTION_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    extracted = await llm.call_structured(messages, ExtractedMemories)

    stored: list[MemoryRecord] = []
    for candidate in extracted.candidates:
        try:
            record = await upsert_memory(
                db,
                tenant_id=tenant_id,
                user_id=None,
                memory_type=MemoryType(candidate.memory_type),
                content=candidate.content,
                provenance=MemoryProvenance.SYSTEM_EXTRACTED,
                confidence=candidate.confidence,
                source_episode_id=source_episode_id,
            )
        except MemoryPolicyViolation as exc:
            logger.warning(
                "memory_candidate_rejected", reason=str(exc), tenant_id=str(tenant_id)
            )
            continue
        stored.append(record)

    return stored
