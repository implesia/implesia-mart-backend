import uuid

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status

from app.api.deps import CurrentUser, DbSession, no_store
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.rate_limit import (
    customer_login_account_key,
    limiter,
    refresh_account_key,
)
from app.schemas.auth import RefreshRequest, TokenPair
from app.schemas.cart import CartRead
from app.schemas.common import Message
from app.schemas.customer import (
    CartMergeRequest,
    CustomerLoginRequest,
    CustomerPasswordChangeRequest,
    CustomerProfileRead,
    CustomerProfileUpdate,
    CustomerRegisterRequest,
    NotificationListResponse,
    NotificationRead,
)
from app.services import (
    cart_service,
    customer_auth_service,
    delivery_service,
    image_storage,
    notification_service,
    pricing_service,
    refresh_token_service,
)
from app.services.cart_service import Shopper

router = APIRouter(dependencies=[Depends(no_store)])


@router.post("/auth/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    db: DbSession,
    payload: CustomerRegisterRequest,
) -> TokenPair:
    user = await customer_auth_service.register_customer(db, payload)
    return await refresh_token_service.issue_session(db, user)


@router.post("/auth/login", response_model=TokenPair)
@limiter.limit(settings.rate_limit_login_ip)
@limiter.limit(settings.rate_limit_login_account, key_func=customer_login_account_key)
async def login(
    request: Request,
    db: DbSession,
    payload: CustomerLoginRequest,
) -> TokenPair:
    del request
    user = await customer_auth_service.authenticate_customer(
        db, payload.identifier, payload.password
    )
    return await refresh_token_service.issue_session(db, user)


@router.post("/auth/refresh", response_model=TokenPair)
@limiter.limit(settings.rate_limit_refresh_ip)
@limiter.limit(settings.rate_limit_refresh_account, key_func=refresh_account_key)
async def refresh(
    request: Request,
    db: DbSession,
    payload: RefreshRequest,
) -> TokenPair:
    del request
    return await refresh_token_service.rotate_session(db, payload.refresh_token)


@router.post("/auth/logout", response_model=Message)
async def logout(
    db: DbSession,
    payload: RefreshRequest,
) -> Message:
    await refresh_token_service.logout_session(db, payload.refresh_token)
    return Message(message="Signed out")


@router.get("/profile", response_model=CustomerProfileRead)
async def read_profile(
    user: CurrentUser,
) -> CustomerProfileRead:
    return CustomerProfileRead.model_validate(user)


@router.patch("/profile", response_model=CustomerProfileRead)
async def update_profile(
    db: DbSession,
    user: CurrentUser,
    payload: CustomerProfileUpdate,
) -> CustomerProfileRead:
    updated = await customer_auth_service.update_profile(db, user, payload)
    return CustomerProfileRead.model_validate(updated)


@router.post("/change-password", response_model=Message, status_code=status.HTTP_200_OK)
async def change_password(
    db: DbSession,
    user: CurrentUser,
    payload: CustomerPasswordChangeRequest,
) -> Message:
    await customer_auth_service.change_password(
        db, user, payload.current_password, payload.new_password
    )
    return Message(message="Password updated")


@router.post("/profile/avatar", response_model=CustomerProfileRead)
async def upload_avatar(
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> CustomerProfileRead:
    image_bytes = await image_storage.read_image(file)
    url = image_storage.store_image(image_bytes, folder="avatars")
    user.avatar_url = url
    await db.commit()
    await db.refresh(user)
    return CustomerProfileRead.model_validate(user)


@router.post("/cart/merge", response_model=CartRead)
async def merge_cart(
    db: DbSession,
    user: CurrentUser,
    payload: CartMergeRequest,
) -> CartRead:
    shopper = Shopper(user=user, guest_token=payload.guest_token)
    cart, _ = await cart_service._open(db, shopper, create=True)
    fees = await delivery_service.fees(db)
    rules = await pricing_service.store_rules(db)
    assert cart is not None
    return cart_service._read(cart, None, fees, rules)


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=100),
) -> NotificationListResponse:
    items, unread_count = await notification_service.get_user_notifications(
        db, user.id, limit=limit
    )
    return NotificationListResponse(
        items=[NotificationRead.model_validate(n) for n in items],
        unread_count=unread_count,
    )


@router.patch("/notifications/{notification_id}/read", response_model=Message)
async def mark_notification_read(
    db: DbSession,
    user: CurrentUser,
    notification_id: uuid.UUID,
) -> Message:
    ok = await notification_service.mark_read(db, notification_id, user.id)
    if not ok:
        raise NotFoundError("Notification not found")
    return Message(message="Notification marked as read")


@router.post("/notifications/mark-all-read", response_model=Message)
async def mark_all_notifications_read(
    db: DbSession,
    user: CurrentUser,
) -> Message:
    count = await notification_service.mark_all_read(db, user.id)
    return Message(message=f"{count} notifications marked as read")
