import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import page_count
from app.schemas.product import OptionChoice, SelectedOption


class CartItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: int = Field(1, ge=1, le=5)
    selection: list[OptionChoice] = Field(default_factory=list, max_length=6)


class CartItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=1, le=5)


class CartItemRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    title: str
    slug: str
    image_src: str
    unit_price: int
    quantity: int
    line_total: int
    available: bool
    selection: list[SelectedOption] = Field(default_factory=list)


class CartRead(BaseModel):
    id: uuid.UUID | None
    anonymous: bool
    cart_token: str | None = None
    items: list[CartItemRead]
    item_count: int
    subtotal: int
    shipping: int
    total: int
    inside_dhaka: int
    dhaka_suburban: int
    outside_dhaka: int
    inside_enabled: bool = True
    suburban_enabled: bool = True
    outside_enabled: bool = True


class CartOwnerRead(BaseModel):
    kind: Literal["user", "guest"]
    user_id: uuid.UUID | None = None
    email: str | None = None
    full_name: str | None = None
    role: str | None = None


class AdminCartItemRead(CartItemRead):
    added_at: datetime


class AdminCartRead(BaseModel):
    id: uuid.UUID
    owner: CartOwnerRead
    items: list[AdminCartItemRead]
    item_count: int
    subtotal: int
    shipping: int
    total: int
    inside_dhaka: int
    dhaka_suburban: int
    outside_dhaka: int
    inside_enabled: bool = True
    suburban_enabled: bool = True
    outside_enabled: bool = True
    created_at: datetime
    updated_at: datetime


class AdminCartMetrics(BaseModel):
    carts: int
    user_carts: int
    guest_carts: int
    units: int


class AdminCartQuery(BaseModel):
    q: str | None = Field(default=None, max_length=80)
    owner: Literal["all", "user", "guest"] = "all"
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(10, ge=1, le=50)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class AdminCartList(BaseModel):
    items: list[AdminCartRead]
    total: int
    page: int
    page_size: int
    pages: int
    metrics: AdminCartMetrics


def cart_page_count(total: int, page_size: int) -> int:
    return page_count(total, page_size)
