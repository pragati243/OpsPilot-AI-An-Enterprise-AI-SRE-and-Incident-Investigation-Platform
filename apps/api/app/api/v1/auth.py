from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import rate_limit_by_client
from app.core.security import InvalidTokenError
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterTenantRequest,
    TokenResponse,
    UserRead,
)
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    TenantSlugTakenError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register-tenant",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(rate_limit_by_client(limit=5, window_seconds=60, scope="register_tenant"))
    ],
)
async def register_tenant(payload: RegisterTenantRequest, db: DbSession) -> UserRead:
    """Bootstrap a new workspace: creates a tenant and its first admin user."""
    service = AuthService(db)
    try:
        _tenant, admin = await service.register_tenant(
            tenant_name=payload.tenant_name,
            tenant_slug=payload.tenant_slug,
            admin_email=payload.admin_email,
            admin_password=payload.admin_password,
            admin_full_name=payload.admin_full_name,
        )
    except TenantSlugTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Tenant slug already taken"
        ) from exc
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc
    return UserRead.model_validate(admin)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit_by_client(limit=10, window_seconds=60, scope="login"))],
)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    service = AuthService(db)
    try:
        user = await service.authenticate(email=payload.email, password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        ) from exc
    return service.issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    service = AuthService(db)
    try:
        return await service.refresh_access_token(payload.refresh_token)
    except (InvalidTokenError, InactiveUserError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
        ) from exc


@router.get("/me", response_model=UserRead)
async def read_current_user(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
