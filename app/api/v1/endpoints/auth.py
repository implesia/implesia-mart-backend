from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, DbSession, no_store
from app.core.config import settings
from app.core.exceptions import PermissionDeniedError
from app.rate_limit import limiter, login_account_key, refresh_account_key
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    TokenPair,
    WSTicketResponse,
)
from app.schemas.common import Message
from app.schemas.user import UserRead
from app.services import permission_service, refresh_token_service, user_service
from app.services.ws_manager import ws_manager

router = APIRouter()


@router.post("/login", response_model=TokenPair)
@limiter.limit(settings.rate_limit_login_ip)
@limiter.limit(settings.rate_limit_login_account, key_func=login_account_key)
async def login(request: Request, db: DbSession, payload: LoginRequest) -> TokenPair:
    del request
    user = await user_service.authenticate(db, payload.email, payload.password)
    if not await permission_service.role_has_admin_access(db, user.role):
        raise PermissionDeniedError("Admin access is restricted to staff accounts")
    return await refresh_token_service.issue_session(db, user)


@router.post("/refresh", response_model=TokenPair)
@limiter.limit(settings.rate_limit_refresh_ip)
@limiter.limit(settings.rate_limit_refresh_account, key_func=refresh_account_key)
async def refresh(request: Request, db: DbSession, payload: RefreshRequest) -> TokenPair:
    del request
    return await refresh_token_service.rotate_session(db, payload.refresh_token, require_staff=True)


@router.post("/logout", response_model=Message)
async def logout(db: DbSession, payload: RefreshRequest) -> Message:
    await refresh_token_service.logout_session(db, payload.refresh_token)
    return Message(message="Signed out")


@router.get("/me", response_model=UserRead)
async def read_current_user(db: DbSession, user: CurrentUser) -> UserRead:
    data = UserRead.model_validate(user)
    data.admin_access = await permission_service.role_has_admin_access(db, user.role)
    data.permissions = await permission_service.get_role_permissions_map(db, user.role)
    return data


@router.post("/change-password", response_model=Message, status_code=status.HTTP_200_OK)
async def change_password(
    db: DbSession, user: CurrentUser, payload: PasswordChangeRequest
) -> Message:
    await user_service.change_password(db, user, payload.current_password, payload.new_password)
    return Message(message="Password updated")


@router.post(
    "/ws-ticket",
    response_model=WSTicketResponse,
    dependencies=[Depends(no_store)],
)
async def issue_staff_ws_ticket(db: DbSession, user: CurrentUser) -> WSTicketResponse:
    """Issue a 30-second single-use WebSocket ticket for authenticated admin staff."""
    return await ws_manager.issue_staff_ticket(db, user)
