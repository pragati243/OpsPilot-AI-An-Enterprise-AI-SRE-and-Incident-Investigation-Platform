import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import MemoryProvenance, MemoryStatus, MemoryType


class MemoryCandidate(BaseModel):
    """One candidate fact proposed by extraction, before the policy engine
    decides whether it's safe and non-duplicate to persist. Only semantic
    and procedural candidates come from extraction — profile memory is
    explicitly set by the user, never inferred from an investigation.
    """

    memory_type: Literal["semantic", "procedural"]
    content: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedMemories(BaseModel):
    """Structured output schema for the learn node's LLM call."""

    candidates: list[MemoryCandidate] = Field(
        default_factory=list,
        max_length=5,
        description="General, reusable facts worth remembering beyond this one incident "
        "(e.g. architecture facts, confirmed fixes). Empty if nothing new and reusable "
        "was learned — don't restate the incident narrative itself, that's the episode.",
    )


class MemoryRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    memory_type: MemoryType
    content: str
    provenance: MemoryProvenance
    confidence: float
    status: MemoryStatus
    superseded_by: uuid.UUID | None
    source_episode_id: uuid.UUID | None
    last_verified_at: datetime | None
    created_at: datetime


class SetProfilePreferenceRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class CorrectMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
