import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.order import OrderStatus
from app.schemas.common import page_count
from app.schemas.inquiry import normalize_phone
from app.schemas.payment import ADVANCE_PERCENTS, AdvanceOption, PaymentMethod
from app.schemas.pricing import QUANTITY_CEILING, Percent
from app.schemas.product import OptionChoice, SelectedOption

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REFERENCE = re.compile(r"^[A-Za-z0-9+\-]{4,64}$")
OrderSourceName = Literal["cart", "direct"]
DeliveryZone = Literal["inside", "suburban", "outside"]


class OrderLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=1, le=QUANTITY_CEILING)
    selection: list[OptionChoice] = Field(default_factory=list, max_length=6)


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
    # "bangla_qr": pay advance_percent now by the admin's QR, the rest on delivery. The
    # amounts are always computed by the server from the order total.
    payment_method: PaymentMethod = "cod"
    advance_percent: int | None = None
    payment_reference: str = Field("", max_length=80)

    @field_validator("payment_reference")
    @classmethod
    def _reference(cls, value: str) -> str:
        return re.sub(r"\s+", "", value)

    @model_validator(mode="after")
    def payment_fields(self) -> "OrderCreate":
        if self.payment_method == "cod":
            if self.advance_percent is not None or self.payment_reference:
                raise ValueError("ক্যাশ অন ডেলিভারিতে অগ্রিম বা ট্রানজেকশন আইডি লাগে না")
            return self
        if self.advance_percent not in ADVANCE_PERCENTS:
            raise ValueError("অগ্রিম ২৫%, ৫০%, ৭৫% বা ১০০% বেছে নিন")
        if not _REFERENCE.fullmatch(self.payment_reference):
            raise ValueError(
                "ট্রানজেকশন আইডি বা যে নম্বর থেকে পাঠিয়েছেন সেটি লিখুন (৪–৬৪ অক্ষর, ইংরেজি অক্ষর/সংখ্যা)"
            )
        return self

    @field_validator("customer_name", "district", "area", "address", "notes", "email")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        phone = normalize_phone(value)
        if phone is None:
            raise ValueError("Phone must be an 11-digit Bangladesh mobile number")
        return phone

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        if value and not _EMAIL.fullmatch(value):
            raise ValueError("Email is invalid")
        return value


class QuoteLineRead(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    sku: str = ""
    cart_item_id: uuid.UUID | None = None
    title: str
    slug: str
    image_src: str
    unit_price: int
    quantity: int
    line_total: int
    available: bool
    max_quantity: int
    selection: list[SelectedOption] = Field(default_factory=list)
    regular_price: int = 0
    base_discount_percent: Percent = Decimal("0.00")
    quantity_discount_percent: Percent = Decimal("0.00")
    total_discount_percent: Percent = Decimal("0.00")


class QuoteRead(BaseModel):
    items: list[QuoteLineRead]
    item_count: int
    subtotal: int
    shipping: int
    total: int
    delivery_zone: DeliveryZone
    delivery_available: bool
    # Bangla QR advance choices for this total (empty when no QR is set or nothing to pay).
    bangla_qr_options: list[AdvanceOption] = Field(default_factory=list)


class OrderItemRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    variant_id: uuid.UUID | None = None
    sku: str = ""
    title: str
    slug: str
    image_src: str
    unit_price: int
    quantity: int
    line_total: int
    selection: list[SelectedOption] = Field(default_factory=list)
    # Price snapshot from when the order was placed. None on orders placed before it existed.
    regular_price: int | None = None
    base_discount_percent: Percent | None = None
    quantity_discount_percent: Percent | None = None
    total_discount_percent: Percent | None = None


class OrderLookup(BaseModel):
    """Public status check. The number alone is not enough."""

    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=4, max_length=32)
    phone: str = Field(min_length=11, max_length=20)

    @field_validator("number")
    @classmethod
    def _number(cls, value: str) -> str:
        number = re.sub(r"\s+", "", value).upper()
        if not re.fullmatch(r"IM-[0-9A-F]{8}", number):
            raise ValueError("Order number looks wrong")
        return number

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        phone = normalize_phone(value)
        if phone is None:
            raise ValueError("Phone must be an 11-digit Bangladesh mobile number")
        return phone


class PublicOrderItemRead(BaseModel):
    title: str
    slug: str
    # Lets the tracking page link to the canonical /products/{id}. None once the product is deleted.
    product_id: uuid.UUID | None = None
    image_src: str
    unit_price: int
    quantity: int
    line_total: int
    selection: list[SelectedOption] = Field(default_factory=list)


class PublicOrderRead(BaseModel):
    """Status, money, and tracking. No street address, area, or notes."""

    number: str
    status: str
    customer_name: str
    phone: str
    delivery_zone: DeliveryZone
    subtotal: int
    shipping: int
    total: int
    courier_name: str
    tracking_number: str
    payment_method: PaymentMethod
    advance_percent: int | None = None
    advance_amount: int = 0
    due_amount: int = 0
    items: list[PublicOrderItemRead]
    created_at: datetime


class OrderRead(BaseModel):
    id: uuid.UUID
    number: str
    source: OrderSourceName
    status: str
    payment_method: PaymentMethod
    advance_percent: int | None = None
    advance_amount: int = 0
    due_amount: int = 0
    payment_reference: str = ""
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
    next_statuses: list[str] = Field(default_factory=list)


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
