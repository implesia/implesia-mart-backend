import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.order import OrderStatus
from app.schemas.common import page_count

_PHONE = re.compile(r"^01\d{9}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OrderSourceName = Literal["cart", "direct"]
DeliveryZone = Literal["inside", "suburban", "outside"]


class OrderLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=5)


class OrderQuoteRequest(BaseModel):
    """A price check. The client never sends a price, a discount, or a fee."""

    model_config = ConfigDict(extra="forbid")

    source: OrderSourceName
    district: str = Field("", max_length=80)
    area: str = Field("", max_length=120)
    delivery_zone: DeliveryZone | None = None
    items: list[OrderLineInput] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def items_match_source(self) -> "OrderQuoteRequest":
        if self.source == "direct" and not self.items:
            raise ValueError("Add at least one product")
        if self.source == "cart" and self.items:
            raise ValueError("A cart order does not accept a product list")
        return self


class OrderCreate(OrderQuoteRequest):
    customer_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=11, max_length=20)
    email: str = Field("", max_length=320)
    district: str = Field(min_length=2, max_length=80)
    area: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=8, max_length=500)
    notes: str = Field("", max_length=500)

    @field_validator("customer_name", "district", "area", "address", "notes", "email")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if not _PHONE.fullmatch(digits):
            raise ValueError("Phone must be an 11-digit Bangladesh mobile number")
        return digits

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        if value and not _EMAIL.fullmatch(value):
            raise ValueError("Email is invalid")
        return value


class QuoteLineRead(BaseModel):
    product_id: uuid.UUID
    cart_item_id: uuid.UUID | None = None
    title: str
    slug: str
    image_src: str
    unit_price: int
    quantity: int
    line_total: int
    available: bool
    max_quantity: int


class QuoteRead(BaseModel):
    items: list[QuoteLineRead]
    item_count: int
    subtotal: int
    shipping: int
    total: int
    delivery_zone: DeliveryZone
    delivery_available: bool


class OrderItemRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    title: str
    slug: str
    image_src: str
    unit_price: int
    quantity: int
    line_total: int


class OrderRead(BaseModel):
    id: uuid.UUID
    number: str
    source: OrderSourceName
    status: str
    payment_method: Literal["cod"]
    anonymous: bool
    customer_name: str
    phone: str
    email: str
    district: str
    area: str
    address: str
    notes: str
    delivery_zone: DeliveryZone
    subtotal: int
    shipping: int
    total: int
    courier_name: str
    tracking_number: str
    items: list[OrderItemRead]
    created_at: datetime


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus | None = None
    courier_name: str | None = Field(default=None, max_length=120)
    tracking_number: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def at_least_one(self) -> "OrderUpdate":
        if self.status is None and self.courier_name is None and self.tracking_number is None:
            raise ValueError("Nothing to update")
        return self

    @field_validator("courier_name", "tracking_number")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class AdminOrderMetrics(BaseModel):
    orders: int
    new: int
    confirmed: int
    shipped: int
    delivered: int
    cancelled: int
    returned: int
    in_transit: int
    revenue: int


class AdminOrderQuery(BaseModel):
    q: str | None = Field(default=None, max_length=80)
    status: OrderStatus | None = None
    scope: Literal["all", "transit"] = "all"
    sort: Literal["newest", "oldest", "high", "low"] = "newest"
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(10, ge=1, le=50)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class AdminOrderList(BaseModel):
    items: list[OrderRead]
    total: int
    page: int
    page_size: int
    pages: int
    metrics: AdminOrderMetrics


def order_page_count(total: int, page_size: int) -> int:
    return page_count(total, page_size)
