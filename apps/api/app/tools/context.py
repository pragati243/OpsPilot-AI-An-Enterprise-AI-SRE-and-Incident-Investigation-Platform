import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@dataclass
class ToolContext:
    """Everything a tool needs to run scoped to one authenticated request.
    Tools never widen their own scope — tenant_id always comes from here,
    never from a tool's input parameters.
    """

    tenant_id: uuid.UUID
    user: User
    db: AsyncSession
