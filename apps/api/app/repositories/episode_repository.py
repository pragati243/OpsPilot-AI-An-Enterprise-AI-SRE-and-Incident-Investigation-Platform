import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode, EpisodeOutcome


class EpisodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_for_incident(
        self, *, tenant_id: uuid.UUID, incident_id: uuid.UUID
    ) -> Episode | None:
        result = await self._session.execute(
            select(Episode)
            .where(Episode.tenant_id == tenant_id, Episode.incident_id == incident_id)
            .order_by(Episode.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        incident_id: uuid.UUID,
        evidence: dict,
        diagnosis: str,
        resolution: str | None,
        outcome: EpisodeOutcome,
        confidence: float,
    ) -> Episode:
        episode = Episode(
            tenant_id=tenant_id,
            incident_id=incident_id,
            evidence=evidence,
            diagnosis=diagnosis,
            resolution=resolution,
            outcome=outcome,
            confidence=confidence,
        )
        self._session.add(episode)
        await self._session.flush()
        return episode
