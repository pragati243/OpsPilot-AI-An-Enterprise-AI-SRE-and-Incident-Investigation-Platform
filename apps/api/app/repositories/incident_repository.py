import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident, IncidentSeverity, IncidentStatus


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, tenant_id: uuid.UUID, incident_id: uuid.UUID) -> Incident | None:
        result = await self._session.execute(
            select(Incident).where(
                Incident.tenant_id == tenant_id, Incident.id == incident_id
            )
        )
        return result.scalar_one_or_none()

    async def search(
        self, *, tenant_id: uuid.UUID, query: str, service: str | None, limit: int
    ) -> list[Incident]:
        stmt = select(Incident).where(Incident.tenant_id == tenant_id)
        if service:
            stmt = stmt.where(Incident.service == service)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                or_(Incident.title.ilike(pattern), Incident.service.ilike(pattern))
            )
        stmt = stmt.order_by(Incident.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        title: str,
        service: str,
        environment: str,
        severity: IncidentSeverity,
        status: IncidentStatus,
        created_by: uuid.UUID | None,
    ) -> Incident:
        incident = Incident(
            tenant_id=tenant_id,
            title=title,
            service=service,
            environment=environment,
            severity=severity,
            status=status,
            created_by=created_by,
        )
        self._session.add(incident)
        await self._session.flush()
        return incident

    async def update_status(
        self, *, incident: Incident, status: IncidentStatus, resolved_at: datetime | None
    ) -> Incident:
        incident.status = status
        incident.resolved_at = resolved_at
        await self._session.flush()
        return incident
