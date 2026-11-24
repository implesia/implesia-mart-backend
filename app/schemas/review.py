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


class AdminReviewProductInfo(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    thumbnail: str | None = None


class AdminReviewCustomerInfo(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str | None = None
    avatar_url: str | None = None


class AdminReviewRead(BaseModel):
    id: uuid.UUID
    rating: int
    headline: str
    comment: str
    is_verified_purchase: bool
    is_published: bool
    created_at: datetime
    updated_at: datetime
    product: AdminReviewProductInfo
    customer: AdminReviewCustomerInfo


class AdminReviewListResponse(BaseModel):
    items: list[AdminReviewRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminReviewUpdate(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    headline: str | None = Field(default=None, max_length=160)
    comment: str | None = Field(default=None, max_length=2000)
    is_published: bool | None = None


class AdminReviewOverview(BaseModel):
    total_reviews: int
    average_rating: float
    published_count: int
    hidden_count: int
    five_star_percent: float
    rating_distribution: dict[str, int]
    products_with_reviews_count: int
    recent_reviews: list[AdminReviewRead]


class AdminProductReviewSummaryRow(BaseModel):
    product_id: uuid.UUID
    name: str
    slug: str
    thumbnail: str | None = None
    review_count: int
    average_rating: float
    published_count: int
    hidden_count: int
    latest_review_at: datetime | None = None


class AdminProductReviewSummaryList(BaseModel):
    items: list[AdminProductReviewSummaryRow]
    total: int
    page: int
    page_size: int
    pages: int
