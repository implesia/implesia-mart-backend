import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request, Response
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import InvalidTokenError, decode_token
from app.db.session import get_db
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix}/auth/login",
    auto_error=False,
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    try:
        payload = decode_token(token, expected_type="access")
        user_id = uuid.UUID(payload["sub"])
    except (InvalidTokenError, ValueError) as exc:
        raise AuthenticationError("Could not validate credentials") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Could not validate credentials")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
) -> User | None:
    """A missing token is a guest. A present but invalid token is still rejected."""
    if not token:
        return None
    return await get_current_user(db, token)


OptionalUser = Annotated[User | None, Depends(get_optional_user)]

# Higher roles inherit everything the roles below them can do.
ROLE_RANK = {UserRole.VIEWER: 0, UserRole.EDITOR: 1, UserRole.SUPERADMIN: 2}


def require_role(
    minimum: UserRole,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    async def dependency(user: CurrentUser) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise PermissionDeniedError(f"This action requires the {minimum.value} role")
        return user

    return dependency


require_editor = require_role(UserRole.EDITOR)
require_superadmin = require_role(UserRole.SUPERADMIN)

RequireEditor = Annotated[User, Depends(require_editor)]
RequireSuperadmin = Annotated[User, Depends(require_superadmin)]


def no_store(response: Response) -> None:
    """Stop shared caches from keeping catalog or admin responses."""
    response.headers["Cache-Control"] = "no-store"


def client_ip(request: Request) -> str | None:
    """Resolve the caller IP, trusting Cloudflare's header when present."""
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )
