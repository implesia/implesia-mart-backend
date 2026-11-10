"""Admin coupon requests and responses.

Code generation is the admin UI's job. This API accepts any code of 3–32
characters from A–Z, 0–9, hyphen and underscore, and stores it in uppercase.

`starts_at` and `ends_at` are inclusive. A value with no timezone is
Asia/Dhaka. A value with an offset is that exact instant.
"""

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator

from app.schemas.common import WriteModel, page_count

DiscountType = Literal["percent", "fixed"]
CouponStatus = Literal["active", "inactive", "expired", "scheduled"]
RedemptionStatus = Literal["active", "cancelled"]
_CODE = re.compile(r"^[A-Z0-9_-]{3,32}$")
_SHOP = ZoneInfo("Asia/Dhaka")


def _number(value: Decimal) -> float:
    return float(value)


CouponAmount = Annotated[
    Decimal,
    PlainSerializer(_number, return_type=float, when_used="json"),
]


def normalize_coupon_code(value: str) -> str:
    code = value.strip().upper()
    if not _CODE.fullmatch(code):
        raise ValueError(
            "কুপন কোড ৩ থেকে ৩২ অক্ষরের হতে হবে। "
            "শুধু ইংরেজি A–Z, সংখ্যা, হাইফেন (-) ও আন্ডারস্কোর (_) চলবে।"
        )
    return code


def as_dhaka(value: datetime | None) -> datetime | None:
    """Naive clocks are Asia/Dhaka. The stored instant is UTC.

    SQLite keeps the wall clock and drops the offset, so a Dhaka wall time
    would be read back six hours late. UTC wall time matches that read.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_SHOP)
    return value.astimezone(UTC)


class CouponWrite(WriteModel):
    code: str = Field(min_length=1, max_length=40)
    discount_type: DiscountType
    value: Decimal = Field(ge=0, le=10_000_000)
    max_discount: int | None = Field(default=None, ge=1, le=10_000_000)
    min_order_amount: int | None = Field(default=None, ge=1, le=10_000_000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    usage_limit_total: int | None = Field(default=None, ge=1, le=1_000_000)
    usage_limit_per_phone: int | None = Field(default=None, ge=1, le=1_000_000)
    first_order_only: bool = False
    product_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    free_delivery: bool = False
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        return normalize_coupon_code(value)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _clock(cls, value: datetime | None) -> datetime | None:
        return as_dhaka(value)

    @field_validator("product_ids", "category_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return _dedupe(value)

    @model_validator(mode="after")
    def _rules(self) -> "CouponWrite":
        check_coupon_shape(
            discount_type=self.discount_type,
            value=self.value,
            max_discount=self.max_discount,
            free_delivery=self.free_delivery,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
        )
        return self


class CouponUpdate(WriteModel):
    """Omitted fields stay as they are. An empty product or category list clears it."""

    code: str | None = Field(default=None, min_length=1, max_length=40)
    discount_type: DiscountType | None = None
    value: Decimal | None = Field(default=None, ge=0, le=10_000_000)
    max_discount: int | None = Field(default=None, ge=1, le=10_000_000)
    min_order_amount: int | None = Field(default=None, ge=1, le=10_000_000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    usage_limit_total: int | None = Field(default=None, ge=1, le=1_000_000)
    usage_limit_per_phone: int | None = Field(default=None, ge=1, le=1_000_000)
    first_order_only: bool | None = None
    product_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    category_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    free_delivery: bool | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_coupon_code(value)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _clock(cls, value: datetime | None) -> datetime | None:
        return as_dhaka(value)

    @field_validator("product_ids", "category_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if value is None:
            return None
        return _dedupe(value)


def check_coupon_shape(
    *,
    discount_type: str,
    value: Decimal,
    max_discount: int | None,
    free_delivery: bool,
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> None:
    exponent = value.as_tuple().exponent
    places = exponent if isinstance(exponent, int) else 0
    if discount_type == "percent":
        if value > 100:
            raise ValueError("শতাংশ ছাড় ০ থেকে ১০০-এর মধ্যে দিন।")
        if places < -2:
            raise ValueError("শতাংশ ছাড় সর্বোচ্চ দুই দশমিক পর্যন্ত।")
    else:
        if max_discount is not None:
            raise ValueError("সর্বোচ্চ ছাড় শুধু শতাংশ কুপনে দেওয়া যায়।")
        if places < 0:
            raise ValueError("নির্দিষ্ট ছাড় পূর্ণ টাকায় দিন, দশমিক ছাড়া।")
    if value <= 0 and not free_delivery:
        raise ValueError("ছাড়ের পরিমাণ দিন, অথবা ফ্রি ডেলিভারি চালু করুন।")
    if starts_at is not None and ends_at is not None and ends_at < starts_at:
        raise ValueError("মেয়াদ শেষের সময় শুরুর সময়ের আগে হতে পারে না।")


class CouponRead(BaseModel):
    id: uuid.UUID
    code: str
    discount_type: DiscountType
    value: CouponAmount
    max_discount: int | None
    min_order_amount: int | None
    starts_at: datetime | None
    ends_at: datetime | None
    usage_limit_total: int | None
    usage_limit_per_phone: int | None
    first_order_only: bool
    product_ids: list[uuid.UUID]
    category_ids: list[uuid.UUID]
    free_delivery: bool
    is_active: bool
    status: CouponStatus
    used_count: int
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CouponList(BaseModel):
    items: list[CouponRead]
    total: int
    page: int
    page_size: int
    pages: int


class CouponQuery(BaseModel):
    q: str | None = Field(default=None, max_length=40)
    status: CouponStatus | None = None
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class CouponRedemptionRead(BaseModel):
    id: uuid.UUID
    coupon_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    phone: str
    discount_amount: int
    status: RedemptionStatus
    cancelled_at: datetime | None
    created_at: datetime


class CouponRedemptionList(BaseModel):
    items: list[CouponRedemptionRead]
    total: int
    page: int
    page_size: int
    pages: int


def coupon_page_count(total: int, page_size: int) -> int:
    return page_count(total, page_size)


def _dedupe(value: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: list[uuid.UUID] = []
    for item in value:
        if item not in seen:
            seen.append(item)
    return seen
