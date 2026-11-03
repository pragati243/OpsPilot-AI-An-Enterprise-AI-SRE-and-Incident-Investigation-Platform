import uuid
from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ServiceStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class Service(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A service in the tenant's simulated production environment.

    `scenario_tag` selects which synthetic log/metric template the simulator
    uses to generate consistent evidence for this service (see
    app/tools/simulator/scenarios.py) — it is deliberately not returned by
    any tool, since the point is for the agent to infer the cause from
    evidence rather than read it off this field.
    """

    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("tenant_id", "name", "environment"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(50), nullable=False, default="production")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    owner_team: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    status: Mapped[ServiceStatus] = mapped_column(
        SAEnum(ServiceStatus, name="service_status"),
        nullable=False,
        default=ServiceStatus.HEALTHY,
    )
    scenario_tag: Mapped[str] = mapped_column(String(100), nullable=False, default="healthy")
