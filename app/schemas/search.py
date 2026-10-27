from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.product import PublicProductCard

SearchType = Literal["all", "products", "blogs"]


class SearchQuery(BaseModel):
    """`q` is optional on purpose: a blank search answers 200 with empty groups."""

    q: str | None = Field(default=None, max_length=100)
    type: SearchType = "all"
    page: int = Field(1, ge=1, le=1000)
    page_size: int = Field(8, ge=1, le=24)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class BlogHit(BaseModel):
    id: str
    slug: str
    title: str
    excerpt: str
    cover_image: str
    cover_alt: str
    author: str
    published_at: str
    read_time: str
    tags: list[str]


class ProductHits(BaseModel):
    items: list[PublicProductCard]
    total: int
    page: int
    pages: int


class BlogHits(BaseModel):
    items: list[BlogHit]
    total: int
    page: int
    pages: int


class SearchResults(BaseModel):
    # The normalised query that was actually searched ("" when the request was blank).
    query: str
    type: SearchType
    page_size: int
    products: ProductHits
    blogs: BlogHits
