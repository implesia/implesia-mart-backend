"""Admin review management. Viewers can read. Moderation writes need editor or above."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, no_store, require_module_access
from app.models.user import User
from app.schemas.review import (
    AdminProductReviewSummaryList,
    AdminReviewListResponse,
    AdminReviewOverview,
    AdminReviewRead,
    AdminReviewUpdate,
)
from app.services import review_service

_ReviewsRead = Annotated[User, Depends(require_module_access("reviews", "read"))]
_ReviewsWrite = Annotated[User, Depends(require_module_access("reviews", "write"))]

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/overview", response_model=AdminReviewOverview)
async def read_reviews_overview(
    db: DbSession,
    user: _ReviewsRead,
) -> AdminReviewOverview:
    del user
    return await review_service.get_admin_overview(db)


@router.get("/by-product", response_model=AdminProductReviewSummaryList)
async def list_reviews_by_product(
    db: DbSession,
    user: _ReviewsRead,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminProductReviewSummaryList:
    del user
    return await review_service.list_admin_reviews_by_product(
        db, q=q, page=page, page_size=page_size
    )


@router.get("", response_model=AdminReviewListResponse)
async def list_reviews(
    db: DbSession,
    user: _ReviewsRead,
    product_id: Annotated[uuid.UUID | None, Query()] = None,
    rating: Annotated[int | None, Query(ge=1, le=5)] = None,
    is_published: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    sort: Annotated[str, Query(pattern="^(newest|oldest|highest|lowest)$")] = "newest",
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminReviewListResponse:
    del user
    return await review_service.list_admin_reviews(
        db,
        product_id=product_id,
        rating=rating,
        is_published=is_published,
        q=q,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.patch("/{review_id}", response_model=AdminReviewRead)
async def update_review(
    db: DbSession,
    actor: _ReviewsWrite,
    review_id: uuid.UUID,
    payload: AdminReviewUpdate,
) -> AdminReviewRead:
    return await review_service.update_admin_review(db, review_id, payload, actor=actor)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    db: DbSession,
    actor: _ReviewsWrite,
    review_id: uuid.UUID,
) -> None:
    await review_service.delete_admin_review(db, review_id, actor=actor)
