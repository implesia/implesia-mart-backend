"""W3C Web Push (VAPID) key and subscription endpoints (admin & customer)."""

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, DbSession, RequireViewer, no_store
from app.schemas.push import (
    PushSubscriptionDeleteRequest,
    PushSubscriptionRead,
    PushSubscriptionUpsertRequest,
    VapidPublicKeyResponse,
)
from app.services import push_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(no_store)])
customer_router = APIRouter(dependencies=[Depends(no_store)])


@public_router.get("/vapid-public-key", response_model=VapidPublicKeyResponse)
async def get_vapid_public_key() -> VapidPublicKeyResponse:
    return VapidPublicKeyResponse(
        enabled=push_service.is_configured(),
        public_key=push_service.public_key(),
    )


@admin_router.post(
    "/push/subscribe",
    response_model=PushSubscriptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_admin_push(
    request: Request,
    db: DbSession,
    staff: RequireViewer,
    payload: PushSubscriptionUpsertRequest,
) -> PushSubscriptionRead:
    ua = payload.user_agent or request.headers.get("user-agent")
    sub = await push_service.upsert_subscription(
        db,
        user_id=staff.id,
        scope="admin",
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=ua,
    )
    return PushSubscriptionRead.model_validate(sub)


@admin_router.delete("/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_admin_push(
    db: DbSession,
    staff: RequireViewer,
    payload: PushSubscriptionDeleteRequest,
) -> None:
    await push_service.delete_subscription(db, user_id=staff.id, endpoint=payload.endpoint)


@customer_router.post(
    "/push/subscribe",
    response_model=PushSubscriptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_customer_push(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    payload: PushSubscriptionUpsertRequest,
) -> PushSubscriptionRead:
    ua = payload.user_agent or request.headers.get("user-agent")
    sub = await push_service.upsert_subscription(
        db,
        user_id=user.id,
        scope="customer",
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=ua,
    )
    return PushSubscriptionRead.model_validate(sub)


@customer_router.delete("/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_customer_push(
    db: DbSession,
    user: CurrentUser,
    payload: PushSubscriptionDeleteRequest,
) -> None:
    await push_service.delete_subscription(db, user_id=user.id, endpoint=payload.endpoint)
