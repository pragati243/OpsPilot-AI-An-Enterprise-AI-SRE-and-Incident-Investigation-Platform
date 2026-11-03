import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service import Service


class ServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_name(
        self, *, tenant_id: uuid.UUID, name: str, environment: str
    ) -> Service | None:
        result = await self._session.execute(
            select(Service).where(
                Service.tenant_id == tenant_id,
                Service.name == name,
                Service.environment == environment,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tenant(self, *, tenant_id: uuid.UUID) -> list[Service]:
        result = await self._session.execute(
            select(Service).where(Service.tenant_id == tenant_id).order_by(Service.name)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        name: str,
        environment: str,
        description: str,
        owner_team: str,
        status: str,
        scenario_tag: str,
    ) -> Service:
        service = Service(
            tenant_id=tenant_id,
            name=name,
            environment=environment,
            description=description,
            owner_team=owner_team,
            status=status,
            scenario_tag=scenario_tag,
        )
        self._session.add(service)
        await self._session.flush()
        return service
