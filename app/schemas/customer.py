import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_BD_PHONE_RE = re.compile(r"^01[3-9]\d{8}$")


def normalize_bd_phone(value: str) -> str:
    """Normalize a Bangladeshi mobile number to standard 11 digits: 01XXXXXXXXX."""
    cleaned = re.sub(r"[\s\-\(\)\.]", "", value.strip())
    if cleaned.startswith("+880"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("880"):
        cleaned = cleaned[2:]
    if not _BD_PHONE_RE.match(cleaned):
        raise ValueError("Enter a valid 11-digit Bangladeshi mobile number (e.g. 01712345678)")
    return cleaned


class CustomerRegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str
    email: EmailStr | None = None
    password: str = Field(min_length=6, max_length=72)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_bd_phone(v)

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip().lower()
        return text if text else None


class CustomerLoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=72)


class CustomerProfileRead(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str | None = None
    email: str | None = None
    district: str | None = None
    area: str | None = None
    address: str | None = None
    avatar_url: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = None
    email: EmailStr | None = None
    district: str | None = Field(default=None, max_length=80)
    area: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    avatar_url: str | None = Field(default=None, max_length=500)

    @field_validator("phone")
    @classmethod
    def validate_phone_if_provided(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        return normalize_bd_phone(str(v))

    @field_validator("email", mode="before")
    @classmethod
    def clean_email_if_provided(cls, v: object) -> str | None:
        if v is None:
            return None
        text = str(v).strip().lower()
        return text if text else None


class CustomerPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


class CustomerOrderItemSummary(BaseModel):
    title: str
    slug: str
    image_src: str
    unit_price: int
    quantity: int
    line_total: int
    sku: str

    model_config = ConfigDict(from_attributes=True)


class CustomerOrderSummary(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    created_at: datetime
    total: int
    payment_method: str
    items_count: int
    courier_name: str
    tracking_number: str
    first_item_image: str | None = None
    first_item_title: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerOrderDetail(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    created_at: datetime
    delivered_at: datetime | None = None
    customer_name: str
    phone: str
    district: str
    area: str
    address: str
    subtotal: int
    shipping: int
    total: int
    coupon_discount: int | None = None
    manual_discount: int = 0
    paid_amount: int = 0
    due_amount: int | None = None
    payment_method: str
    courier_name: str
    tracking_number: str
    items: list[CustomerOrderItemSummary]

    model_config = ConfigDict(from_attributes=True)


class CustomerDashboardStats(BaseModel):
    total_orders: int
    active_orders: int
    total_spent: int
    customer_name: str
    phone: str | None = None
    email: str | None = None


class NotificationRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    order_id: uuid.UUID | None = None
    type: str
    title: str
    message: str
    is_read: bool
    language: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    unread_count: int


class MarkNotificationReadRequest(BaseModel):
    notification_id: uuid.UUID | None = None


class PurchasedProductItem(BaseModel):
    product_id: uuid.UUID
    title: str
    slug: str
    image_url: str | None = None
    price: int
    purchased_at: datetime
    order_number: str
    payment_method: str
    can_review: bool


class TrackingTimelineStep(BaseModel):
    status: str
    label: str
    description: str
    timestamp: datetime | None = None
    completed: bool


class OrderTrackingDetail(BaseModel):
    order_number: str
    status: str
    courier_name: str
    tracking_number: str
    timeline: list[TrackingTimelineStep]


class CartMergeRequest(BaseModel):
    guest_token: str

