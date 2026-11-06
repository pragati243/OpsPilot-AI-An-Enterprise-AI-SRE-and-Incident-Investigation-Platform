import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import AgentLLM, LLMNotConfiguredError, build_groq_llm
from app.core.security import InvalidTokenError, TokenType, decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    db: DbSession,
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_error

    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise credentials_error from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise credentials_error from exc

    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise credentials_error

    # Every log line emitted for the rest of this request now carries
    # tenant_id/user_id — the audit trail half of tenant isolation
    # (the enforcement half is each repository's tenant_id WHERE clause).
    structlog.contextvars.bind_contextvars(
        tenant_id=str(user.tenant_id), user_id=str(user.id)
    )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_agent_llm() -> AgentLLM:
    """Separate dependency (rather than building it inline in each route) so
    tests can override this with a scripted fake and never need a real
    GROQ_API_KEY to exercise the investigation endpoint.

    Dependency resolution happens before a route's own try/except runs, so
    a missing API key has to be turned into a clean HTTPException right
    here — otherwise it reaches the client as a bare 500 with an internal
    OpenAI SDK stack trace instead of an actionable message.
    """
    try:
        return build_groq_llm()
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation service is not configured (missing LLM credentials).",
        ) from exc


AgentLLMDep = Annotated[AgentLLM, Depends(get_agent_llm)]


def require_role(
    *allowed_roles: UserRole,
) -> Callable[[CurrentUser], Coroutine[Any, Any, User]]:
    async def _check(user: CurrentUser) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return _check
