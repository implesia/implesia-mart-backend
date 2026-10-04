import ipaddress
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
    """Keep private responses out of shared caches.

    Admin, cart, and order routes use this. Public CMS reads under ``/home``
    and ``/pages`` are uncached for now. A later cache is only those public
    GETs, for 30 seconds or with an ETag. Do not put that cache on these routes.
    """
    response.headers["Cache-Control"] = "no-store"


def client_ip(request: Request) -> str | None:
    """Return the caller address.

    Forwarded headers count only when the socket peer is a trusted proxy.
    A proxy that appends the connecting address cannot be fooled by a fake
    address placed at the front of ``X-Forwarded-For``.
    """
    peer = _parse_ip(request.client.host) if request.client is not None else None
    if peer is None:
        return request.client.host if request.client is not None else None
    if not _is_trusted(peer):
        return str(peer)

    chain = _forwarded_chain(request)
    seen_by_proxy = _nearest_untrusted(chain)
    cloudflare = _parse_ip(request.headers.get("cf-connecting-ip") or "")
    cloudflare_agrees = seen_by_proxy is None or cloudflare == seen_by_proxy
    if cloudflare is not None and not _is_trusted(cloudflare) and cloudflare_agrees:
        return str(cloudflare)
    if seen_by_proxy is not None:
        return str(seen_by_proxy)
    return str(peer)


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _trusted_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in settings.trusted_proxies:
        try:
            network = ipaddress.ip_network(item.strip(), strict=False)
        except ValueError:
            continue
        if network.prefixlen == 0:
            continue
        networks.append(network)
    return networks


def _is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(address in network for network in _trusted_networks())


def _forwarded_chain(
    request: Request,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    raw = request.headers.get("x-forwarded-for") or ""
    return [parsed for part in raw.split(",") if (parsed := _parse_ip(part)) is not None]


def _nearest_untrusted(
    chain: list[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    for hop in reversed(chain):
        if not _is_trusted(hop):
            return hop
    return None
