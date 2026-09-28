import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.schemas.auth import LoginRequest, PasswordChangeRequest, RefreshRequest, TokenPair
from app.schemas.common import Message
from app.schemas.user import UserRead
from app.services import user_service

router = APIRouter()


def _token_pair(user_id: uuid.UUID) -> TokenPair:
    subject = str(user_id)
    return TokenPair(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenPair)
async def login(db: DbSession, payload: LoginRequest) -> TokenPair:
    user = await user_service.authenticate(db, payload.email, payload.password)
    return _token_pair(user.id)


@router.post("/refresh", response_model=TokenPair)
async def refresh(db: DbSession, payload: RefreshRequest) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
        user_id = uuid.UUID(claims["sub"])
    except (InvalidTokenError, ValueError) as exc:
        raise AuthenticationError("Invalid refresh token") from exc

    user = await user_service.get_by_id(db, user_id)
    if not user.is_active:
        raise AuthenticationError("This account is disabled")
    return _token_pair(user.id)


@router.get("/me", response_model=UserRead)
async def read_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post("/change-password", response_model=Message, status_code=status.HTTP_200_OK)
async def change_password(
    db: DbSession, user: CurrentUser, payload: PasswordChangeRequest
) -> Message:
    await user_service.change_password(db, user, payload.current_password, payload.new_password)
    return Message(message="Password updated")
