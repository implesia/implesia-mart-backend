import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, DbSession, no_store
from app.schemas.review import (
    CanReviewResponse,
    ProductReviewCreate,
    ProductReviewPage,
    ProductReviewRead,
)
from app.services import review_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/products/{product_id}/reviews", response_model=ProductReviewPage)
async def list_product_reviews(
    db: DbSession,
    product_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> ProductReviewPage:
    return await review_service.get_product_reviews(
        db, product_id, page=page, page_size=page_size
    )


@router.get("/products/{product_id}/can-review", response_model=CanReviewResponse)
async def check_can_review(
    db: DbSession,
    user: CurrentUser,
    product_id: uuid.UUID,
) -> CanReviewResponse:
    return await review_service.verify_purchaser(db, user.id, product_id)


@router.post(
    "/products/{product_id}/reviews",
    response_model=ProductReviewRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_review(
    db: DbSession,
    user: CurrentUser,
    product_id: uuid.UUID,
    payload: ProductReviewCreate,
) -> ProductReviewRead:
    return await review_service.submit_review(db, user.id, product_id, payload)
