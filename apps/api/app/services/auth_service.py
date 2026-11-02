import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse


class TenantSlugTakenError(Exception):
    pass


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InactiveUserError(Exception):
    pass


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenants = TenantRepository(session)
        self._users = UserRepository(session)

    async def register_tenant(
        self,
        *,
        tenant_name: str,
        tenant_slug: str,
        admin_email: str,
        admin_password: str,
        admin_full_name: str,
    ) -> tuple[Tenant, User]:
        if await self._tenants.get_by_slug(tenant_slug) is not None:
            raise TenantSlugTakenError(tenant_slug)
        if await self._users.get_by_email(admin_email) is not None:
            raise EmailAlreadyRegisteredError(admin_email)

        tenant = await self._tenants.create(name=tenant_name, slug=tenant_slug)
        admin = await self._users.create(
            tenant_id=tenant.id,
            email=admin_email,
            hashed_password=hash_password(admin_password),
            full_name=admin_full_name,
            role=UserRole.ADMIN,
        )
        await self._session.commit()
        return tenant, admin

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self._users.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InactiveUserError()
        return user

    def issue_tokens(self, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=create_access_token(
                subject=user.id, tenant_id=user.tenant_id, role=user.role.value
            ),
            refresh_token=create_refresh_token(
                subject=user.id, tenant_id=user.tenant_id, role=user.role.value
            ),
        )

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        user = await self._users.get_by_id(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise InactiveUserError()
        return self.issue_tokens(user)
