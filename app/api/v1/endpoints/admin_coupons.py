"""Admin coupons. Viewers can read. Writes need editor or above.

Successful writes are recorded by the router audit dependency.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, RequireEditor, no_store
from app.schemas.coupon import (
    CouponList,
    CouponQuery,
    CouponRead,
    CouponRedemptionList,
    CouponUpdate,
    CouponWrite,
)
from app.services import coupon_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("", response_model=CouponList)
async def list_coupons(
    db: DbSession, user: CurrentUser, query: Annotated[CouponQuery, Depends()]
) -> CouponList:
    del user
    return await coupon_service.list_coupons(db, query)


@router.post("", response_model=CouponRead, status_code=201)
async def create_coupon(
    db: DbSession, actor: RequireEditor, payload: CouponWrite
) -> CouponRead:
    return await coupon_service.create_coupon(db, payload, actor)


@router.get("/{coupon_id}", response_model=CouponRead)
async def get_coupon(db: DbSession, user: CurrentUser, coupon_id: uuid.UUID) -> CouponRead:
    del user
    return await coupon_service.get_coupon(db, coupon_id)


@router.patch("/{coupon_id}", response_model=CouponRead)
async def update_coupon(
    db: DbSession,
    actor: RequireEditor,
    coupon_id: uuid.UUID,
    payload: CouponUpdate,
) -> CouponRead:
    del actor
    return await coupon_service.update_coupon(db, coupon_id, payload)


@router.post("/{coupon_id}/activate", response_model=CouponRead)
async def activate_coupon(
    db: DbSession, actor: RequireEditor, coupon_id: uuid.UUID
) -> CouponRead:
    del actor
    return await coupon_service.set_active(db, coupon_id, True)


@router.post("/{coupon_id}/deactivate", response_model=CouponRead)
async def deactivate_coupon(
    db: DbSession, actor: RequireEditor, coupon_id: uuid.UUID
) -> CouponRead:
    del actor
    return await coupon_service.set_active(db, coupon_id, False)


@router.get("/{coupon_id}/redemptions", response_model=CouponRedemptionList)
async def list_redemptions(
    db: DbSession,
    user: CurrentUser,
    coupon_id: uuid.UUID,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CouponRedemptionList:
    del user
    return await coupon_service.list_redemptions(
        db, coupon_id, page=page, page_size=page_size
    )
