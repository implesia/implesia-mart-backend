import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5, description="Rating from 1 to 5 stars")
    headline: str = Field(default="", max_length=160)
    comment: str = Field(default="", max_length=2000)


class ProductReviewRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    user_avatar: str | None = None
    rating: int
    headline: str
    comment: str
    is_verified_purchase: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductReviewSummary(BaseModel):
    average_rating: float
    total_reviews: int
    rating_histogram: dict[str, int]


class ProductReviewPage(BaseModel):
    items: list[ProductReviewRead]
    summary: ProductReviewSummary
    total: int
    page: int
    page_size: int
    pages: int


class CanReviewResponse(BaseModel):
    can_review: bool
    reason: str
    order_id: uuid.UUID | None = None
