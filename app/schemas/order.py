import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.order import CallStatus, OrderStatus
from app.schemas.common import page_count
from app.schemas.inquiry import normalize_phone
from app.schemas.payment import (
    ADVANCE_PERCENTS,
    AdvanceOption,
    AnyPaymentMethod,
    OfflinePaymentMethod,
    PaymentMethod,
)
from app.schemas.pricing import QUANTITY_CEILING, Percent
from app.schemas.product import OptionChoice, SelectedOption
from app.schemas.report import ReportMoney

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REFERENCE = re.compile(r"^[A-Za-z0-9+\-]{4,64}$")
OrderSourceName = Literal["cart", "direct"]
DeliveryZone = Literal["inside", "suburban", "outside"]
_TRACKING_LIMIT = 500


def purchase_event_id(order_number: str) -> str:
    """Shared with the browser Pixel so Meta can deduplicate the Purchase."""
    return f"purchase_{order_number}"


class OrderTracking(BaseModel):
    """Optional browser context for the Purchase event. Invalid values are dropped."""

    model_config = ConfigDict(extra="ignore")

    fbp: str | None = None
    fbc: str | None = None
    event_source_url: str | None = None

    @field_validator("fbp", "fbc", "event_source_url", mode="before")
    @classmethod
    def _optional_text(cls, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text or len(text) > _TRACKING_LIMIT:
            return None
        return text


class OrderLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=1, le=QUANTITY_CEILING)
    selection: list[OptionChoice] = Field(default_factory=list, max_length=6)


class CouponQuoteRead(BaseModel):
    """The coupon on a quote. An invalid code does not fail the quote."""

    code: str
    valid: bool
    discount: int = 0
    free_delivery: bool = False
    error_code: str | None = None
    message: str | None = None


class OrderQuoteRequest(BaseModel):
    """A price check. The client never sends a price, a discount, or a fee.

    `coupon_code` is the only coupon input. A client-sent discount or total is
    rejected (unknown field), and the server computes the taka itself.
    Optional `phone` lets the quote check the per-phone limit and first-order
    rule. Order create always has a phone, so those two are always checked there.
    """

    model_config = ConfigDict(extra="forbid")

    source: OrderSourceName
    district: str = Field("", max_length=80)
    area: str = Field("", max_length=120)
    delivery_zone: DeliveryZone | None = None
    items: list[OrderLineInput] = Field(default_factory=list, max_length=12)
    coupon_code: str | None = Field(default=None, max_length=40)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("coupon_code", "phone")
    @classmethod
    def _blank_coupon(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

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
    # Browser Pixel cookies and the page URL. Omitted by older clients.
    tracking: OrderTracking | None = None

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

    @field_validator("tracking", mode="before")
    @classmethod
    def _tracking(cls, value: object) -> object:
        if value is None or isinstance(value, dict | OrderTracking):
            return value
        return None


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
    # Computed from the total after a valid coupon.
    bangla_qr_options: list[AdvanceOption] = Field(default_factory=list)
    # Null when the shopper did not send a code. Invalid codes stay on this object.
    coupon: CouponQuoteRead | None = None


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
    """Public status check. The number alone is not enough.

    Send the order number or the courier tracking id, plus the phone.
    Both pieces are required. Sending neither, or sending both, is rejected.
    """

    model_config = ConfigDict(extra="forbid")

    number: str | None = Field(default=None, max_length=32)
    tracking_number: str | None = Field(default=None, max_length=120)
    phone: str = Field(min_length=11, max_length=20)

    @field_validator("number", mode="before")
    @classmethod
    def _number(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        number = re.sub(r"\s+", "", value).upper()
        if not number:
            return None
        if not re.fullmatch(r"IM-[0-9A-F]{8}", number):
            raise ValueError("Order number looks wrong")
        return number

    @field_validator("tracking_number", mode="before")
    @classmethod
    def _tracking(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        phone = normalize_phone(value)
        if phone is None:
            raise ValueError("Phone must be an 11-digit Bangladesh mobile number")
        return phone

    @model_validator(mode="after")
    def _one_identifier(self) -> "OrderLookup":
        if (self.number is None) == (self.tracking_number is None):
            raise ValueError("Send the order number or the tracking number, and the phone")
        return self


class PublicOrderItemRead(BaseModel):
    title: str
    slug: str
    # Lets the tracking page link to the canonical /products/{id}. None once the product is deleted.
    product_id: uuid.UUID | None = None
    image_src: str
    unit_price: int
    quantity: int
    line_total: int
    # Option labels joined with " / ". Empty when the line has no options.
    variant_label: str = ""
    selection: list[SelectedOption] = Field(default_factory=list)


class PublicTimelineEvent(BaseModel):
    """One status the customer can see, with the time we actually know.

    No actor, note, or other staff field.
    """

    status: str
    at: datetime


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
    # Null on orders placed with no coupon, including every order from before coupons.
    coupon_code: str | None = None
    coupon_discount: int | None = None
    courier_name: str
    tracking_number: str
    payment_method: AnyPaymentMethod
    advance_percent: int | None = None
    advance_amount: int = 0
    # Cash still to collect. For COD this is the amount due on delivery.
    due_amount: int = 0
    items: list[PublicOrderItemRead]
    # Known status times only. Older orders may have just the placed event.
    timeline: list[PublicTimelineEvent] = Field(default_factory=list)
    created_at: datetime


class OrderRead(BaseModel):
    id: uuid.UUID
    number: str
    source: OrderSourceName
    # online: checkout. offline: entered by staff. Not `source` (cart vs direct).
    origin: Literal["online", "offline"] = "online"
    status: str
    call_status: CallStatus = CallStatus.NOT_CALLED
    payment_method: AnyPaymentMethod
    payment_status: Literal["unpaid", "partial", "paid"] = "unpaid"
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
    coupon_code: str | None = None
    coupon_discount: int | None = None
    # Staff discount, whole taka. 0 on checkout orders. Already taken off `total`.
    manual_discount: int = 0
    paid_amount: int = 0
    courier_name: str
    tracking_number: str
    printed_at: datetime | None = None
    ordered_at: datetime | None = None
    items: list[OrderItemRead]
    created_at: datetime
    customer_history: "CustomerHistory" = Field(default_factory=lambda: CustomerHistory(phone=""))
    duplicate_warning: bool = False
    activity: list["OrderActivityRead"] = Field(default_factory=list)
    # First time the order was delivered or returned. Null until that happens, and on orders
    # whose change was never recorded. Public order lookup does not include these.
    delivered_at: datetime | None = None
    returned_at: datetime | None = None
    next_statuses: list[str] = Field(default_factory=list)
    # Same string as ``number``. Present so the storefront contract can read ``order_number``.
    order_number: str
    analytics_event_id: str


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus | None = None
    call_status: CallStatus | None = None
    courier_name: str | None = Field(default=None, max_length=120)
    tracking_number: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)
    notify_customer: bool = False
    notification_language: str = "bn"

    @model_validator(mode="after")
    def at_least_one(self) -> "OrderUpdate":
        if (
            self.status is None
            and self.call_status is None
            and self.courier_name is None
            and self.tracking_number is None
            and self.notes is None
        ):
            raise ValueError("Nothing to update")
        return self

    @field_validator("courier_name", "tracking_number", "notes")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class AdminOrderMetrics(BaseModel):
    orders: int
    new: int
    confirmed: int
    packed: int = 0
    shipped: int
    delivered: int
    cancelled: int
    returned: int
    in_transit: int
    revenue: int


class StatusCounts(BaseModel):
    new: int = 0
    confirmed: int = 0
    packed: int = 0
    shipped: int = 0
    delivered: int = 0
    cancelled: int = 0
    returned: int = 0


class AdminOrderQuery(BaseModel):
    q: str | None = Field(default=None, max_length=80)
    status: OrderStatus | None = None
    origin: Literal["online", "offline"] | None = None
    payment_method: AnyPaymentMethod | None = None
    payment_status: Literal["unpaid", "partial", "paid"] | None = None
    call_status: CallStatus | None = None
    courier: str | None = Field(default=None, max_length=120)
    date_from: date | None = None
    date_to: date | None = None
    scope: Literal["all", "transit"] = "all"
    sort: Literal["newest", "oldest", "high", "low"] = "newest"
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(10, ge=1, le=50)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @field_validator("courier")
    @classmethod
    def _courier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _dates(self) -> "AdminOrderQuery":
        if self.date_from is not None and self.date_to is not None:
            if self.date_from > self.date_to:
                raise ValueError("date_from is after date_to")
            if (self.date_to - self.date_from).days > 366:
                raise ValueError("Date range is longer than 366 days")
        return self


class AdminOrderList(BaseModel):
    items: list[OrderRead]
    total: int
    page: int
    page_size: int
    pages: int
    metrics: AdminOrderMetrics
    # Counts for the current filters, ignoring the status filter so the tabs stay filled.
    status_counts: StatusCounts = Field(default_factory=StatusCounts)


def order_page_count(total: int, page_size: int) -> int:
    return page_count(total, page_size)


class NewOrderQuery(BaseModel):
    """Cursor for the staff new-order feed. This is not a page of the order list."""

    since: datetime | None = None
    limit: int = Field(20, ge=1, le=50)

    @field_validator("since")
    @classmethod
    def _since_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class NewOrderItem(BaseModel):
    id: uuid.UUID
    number: str
    customer_name: str
    total: int
    payment_method: AnyPaymentMethod
    created_at: datetime


class NewOrderFeed(BaseModel):
    now: datetime
    items: list[NewOrderItem]


_MONEY_CAP = 2_000_000_000


class CustomerHistory(BaseModel):
    phone: str
    total_orders: int = 0
    delivered: int = 0
    # Returned plus cancelled. One number, as the fraud screen asks for both together.
    returned_cancelled: int = 0


class OrderActivityRead(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_name: str | None = None
    action: str
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AdminOrderLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=1, le=QUANTITY_CEILING)
    selection: list[OptionChoice] = Field(default_factory=list, max_length=6)
    # Omitted: the server uses the current selling price, including quantity tiers.
    # Set: this whole-taka unit price is charged and line_total is price × quantity.
    unit_price: int | None = Field(default=None, ge=0, le=_MONEY_CAP)


class OfflineOrderCreate(BaseModel):
    """An order typed by staff. Totals are computed on the server."""

    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=11, max_length=20)
    email: str = Field("", max_length=320)
    district: str = Field(min_length=2, max_length=80)
    area: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=8, max_length=500)
    notes: str = Field("", max_length=500)
    items: list[AdminOrderLineInput] = Field(min_length=1, max_length=12)
    manual_discount: int = Field(0, ge=0, le=_MONEY_CAP)
    # Omitted: the delivery-zone fee. Set: this whole-taka charge, including 0.
    delivery_charge: int | None = Field(default=None, ge=0, le=_MONEY_CAP)
    payment_method: OfflinePaymentMethod
    paid_amount: int = Field(ge=0, le=_MONEY_CAP)
    payment_reference: str = Field("", max_length=80)
    order_date: date | None = None

    @field_validator("payment_reference")
    @classmethod
    def _reference(cls, value: str) -> str:
        return re.sub(r"\s+", "", value)

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

    @model_validator(mode="after")
    def _reference_shape(self) -> "OfflineOrderCreate":
        if self.payment_reference and not _REFERENCE.fullmatch(self.payment_reference):
            raise ValueError("Payment reference must be 4–64 letters, digits, + or -")
        return self


class OrderItemsUpdate(BaseModel):
    """Replace the lines of an order that is still new. Totals are recomputed."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminOrderLineInput] = Field(min_length=1, max_length=12)
    manual_discount: int | None = Field(default=None, ge=0, le=_MONEY_CAP)
    delivery_charge: int | None = Field(default=None, ge=0, le=_MONEY_CAP)


class OrderIdList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _unique(self) -> "OrderIdList":
        self.ids = list(dict.fromkeys(self.ids))
        return self


class BulkStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _unique(self) -> "BulkStatusRequest":
        self.ids = list(dict.fromkeys(self.ids))
        return self


class BulkStatusItem(BaseModel):
    id: uuid.UUID
    ok: bool
    status: str | None = None
    error: str | None = None


class BulkStatusResult(BaseModel):
    results: list[BulkStatusItem]


class PrintedResult(BaseModel):
    printed: list[uuid.UUID]
    missing: list[uuid.UUID]


class PrintLine(BaseModel):
    # Product name, as snapshotted on the line (`title`).
    title: str
    # Option labels joined with " / ". Empty when the line has no options.
    variant_label: str = ""
    sku: str
    # First 8 hex characters of the product UUID. Empty when the product was deleted.
    product_id_short: str = ""
    quantity: int
    unit_price: int
    line_total: int
    selection: list[SelectedOption] = Field(default_factory=list)


class PrintOrder(BaseModel):
    id: uuid.UUID
    # INV- plus the order number's hex body. Derived. Not a separate sequence.
    invoice_id: str
    number: str
    # Same string as `number`.
    order_number: str
    status: str
    origin: Literal["online", "offline"]
    ordered_at: datetime | None
    created_at: datetime
    # Order date in Asia/Dhaka plus the zone's day count. Not stored on the order.
    estimated_delivery_date: date
    customer_name: str
    phone: str
    # Empty when the order has no email.
    email: str = ""
    district: str
    area: str
    address: str
    # address, area, district, skipping blanks.
    full_address: str
    notes: str
    courier_name: str
    tracking_number: str
    payment_method: AnyPaymentMethod
    payment_status: Literal["unpaid", "partial", "paid"]
    subtotal: int
    manual_discount: int
    coupon_discount: int | None
    shipping: int
    total: int
    paid_amount: int
    due_amount: int
    items: list[PrintLine]


class PrintData(BaseModel):
    orders: list[PrintOrder]
    missing: list[uuid.UUID]


class PeriodTotals(BaseModel):
    orders: int
    revenue: int


class OriginSplit(BaseModel):
    origin: Literal["online", "offline"]
    orders: int
    revenue: int


class OverviewOrder(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    origin: Literal["online", "offline"]
    total: int
    customer_name: str
    phone: str
    created_at: datetime
    ordered_at: datetime | None


class OrderOverview(BaseModel):
    timezone: Literal["Asia/Dhaka"] = "Asia/Dhaka"
    today: PeriodTotals
    week: PeriodTotals
    month: PeriodTotals
    pending_confirm: int
    ready_to_pack: int
    shipped: int
    return_rate_percent: ReportMoney | None
    cancel_rate_percent: ReportMoney | None
    origins: list[OriginSplit]
    status_counts: StatusCounts
    recent: list[OverviewOrder]


class CustomerMatch(BaseModel):
    phone: str
    customer_name: str
    email: str
    district: str
    area: str
    address: str
    orders: int
    last_ordered_at: datetime


class CustomerSearchQuery(BaseModel):
    q: str = Field(min_length=2, max_length=80)


class CustomerSearch(BaseModel):
    items: list[CustomerMatch]


OrderRead.model_rebuild()
