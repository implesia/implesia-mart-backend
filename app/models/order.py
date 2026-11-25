import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.product import Product
from app.models.user import User


class OrderStatus(StrEnum):
    NEW = "new"
    CONFIRMED = "confirmed"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


# Allowed forward moves. Cancelled and returned are terminal: their stock is already restored.
# Confirmed is the ready-to-pack queue. Packed is required before shipped.
# Existing rows stay on whatever status they already have; only new moves use this map.
ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    OrderStatus.NEW.value: frozenset({OrderStatus.CONFIRMED.value, OrderStatus.CANCELLED.value}),
    OrderStatus.CONFIRMED.value: frozenset({OrderStatus.PACKED.value, OrderStatus.CANCELLED.value}),
    OrderStatus.PACKED.value: frozenset({OrderStatus.SHIPPED.value, OrderStatus.CANCELLED.value}),
    OrderStatus.SHIPPED.value: frozenset({OrderStatus.DELIVERED.value, OrderStatus.RETURNED.value}),
    OrderStatus.DELIVERED.value: frozenset({OrderStatus.RETURNED.value}),
    OrderStatus.CANCELLED.value: frozenset(),
    OrderStatus.RETURNED.value: frozenset(),
}
_STATUS_ORDER = [status.value for status in OrderStatus]


def next_statuses(current: str) -> list[str]:
    allowed = ORDER_TRANSITIONS.get(current, frozenset())
    return [status for status in _STATUS_ORDER if status in allowed]


class OrderSource(StrEnum):
    """How the lines were chosen. Not online vs offline. See OrderOrigin."""

    CART = "cart"
    DIRECT = "direct"


class OrderOrigin(StrEnum):
    """Where the order was entered. Existing rows are online."""

    ONLINE = "online"
    OFFLINE = "offline"


class CallStatus(StrEnum):
    NOT_CALLED = "not_called"
    CONFIRMED = "confirmed"
    NO_ANSWER = "no_answer"
    FAKE = "fake"


class ActivityAction(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    CALL_STATUS_CHANGED = "call_status_changed"
    ITEMS_EDITED = "items_edited"
    COURIER_EDITED = "courier_edited"
    PRINTED = "printed"
    NOTE_CHANGED = "note_changed"
    CUSTOMER_MESSAGE = "customer_message"
    PAYMENT_UPDATED = "payment_updated"
    COURIER_BOOKED = "courier_booked"
    COURIER_WEBHOOK = "courier_webhook"
    RETURN_REQUESTED = "return_requested"


# Reports group by channel. It is not `orders.source` (cart vs direct)
# and it is not `orders.origin` (online vs offline).
WEBSITE_CHANNEL = "website"
OFFLINE_CHANNEL = "offline"

ONLINE_PAYMENT_METHODS = frozenset({"cod", "bangla_qr"})
OFFLINE_PAYMENT_METHODS = frozenset({"cash", "bkash", "nagad", "card", "due"})
PAYMENT_METHODS = ONLINE_PAYMENT_METHODS | OFFLINE_PAYMENT_METHODS


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A cash-on-delivery or Bangla QR order. Money columns are a snapshot from the server.

    Bangla QR: the shopper pays `advance_amount` (advance_percent of the total, rounded up to
    whole taka) by QR and the rest, `due_amount`, in cash on delivery. COD: advance 0, due =
    total. `due_amount` is NULL on orders placed before this was recorded (due = total).
    """

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("number", name="uq_orders_number"),
        CheckConstraint(
            "status IN ('new', 'confirmed', 'packed', 'shipped', 'delivered', "
            "'cancelled', 'returned')",
            name="status_known",
        ),
        CheckConstraint("source IN ('cart', 'direct')", name="source_known"),
        CheckConstraint(
            "subtotal >= 0 AND shipping >= 0 AND total >= 0", name="money_non_negative"
        ),
        CheckConstraint(
            "payment_method IN ('cod', 'bangla_qr', 'cash', 'bkash', 'nagad', 'card', 'due')",
            name="payment_known",
        ),
        CheckConstraint(
            "advance_percent IS NULL OR advance_percent IN (25, 50, 75, 100)",
            name="advance_percent_known",
        ),
        CheckConstraint(
            "advance_amount >= 0 AND (due_amount IS NULL OR due_amount >= 0)",
            name="advance_non_negative",
        ),
        CheckConstraint(
            "coupon_discount IS NULL OR coupon_discount >= 0",
            name="coupon_discount_non_negative",
        ),
        CheckConstraint("origin IN ('online', 'offline')", name="origin_known"),
        CheckConstraint(
            "call_status IN ('not_called', 'confirmed', 'no_answer', 'fake')",
            name="call_status_known",
        ),
        CheckConstraint("manual_discount >= 0", name="manual_discount_non_negative"),
        CheckConstraint("paid_amount >= 0", name="paid_non_negative"),
        Index("ix_orders_phone", "phone"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_delivered_at", "delivered_at"),
        Index("ix_orders_returned_at", "returned_at"),
        Index("ix_orders_origin", "origin"),
        Index("ix_orders_call_status", "call_status"),
        Index("ix_orders_ordered_at", "ordered_at"),
        # Public lookup compares lower(tracking_number). A plain index would not serve that.
        Index("ix_orders_tracking_number_lower", text("lower(tracking_number)")),
    )

    number: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # Online checkout vs an order typed by staff. NOT NULL, default online,
    # so rows from before this column existed read as online. This is not
    # `source` (cart vs direct) and not `channel`.
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OrderOrigin.ONLINE.value, server_default="online"
    )
    # Where the sale came from. New checkout orders store "website".
    # Orders placed before this column existed stay NULL. No server default:
    # a default would make those old rows read as "website".
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OrderStatus.NEW.value)
    call_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CallStatus.NOT_CALLED.value,
        server_default=CallStatus.NOT_CALLED.value,
    )
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, default="cod")
    advance_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    advance_amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    due_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Bangla QR transaction ID or sender number typed by the shopper. Empty for COD.
    payment_reference: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    district: Mapped[str] = mapped_column(String(80), nullable=False)
    area: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    delivery_zone: Mapped[str] = mapped_column(String(16), nullable=False)
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    # Snapshot of the coupon accepted at checkout. NULL when the order used none,
    # including every order placed before coupons existed. The total already
    # has this discount taken off. A later edit of the coupon does not change it.
    coupon_code: Mapped[str | None] = mapped_column(String(32))
    coupon_discount: Mapped[int | None] = mapped_column(Integer)
    # Staff discount on top of any coupon, whole taka. 0 on every older order
    # and on online checkout. The total already has it taken off.
    manual_discount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Taka already collected. 0 when it was never recorded (older COD orders).
    # A Bangla QR order with paid_amount 0 is read as advance_amount.
    paid_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    courier_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    tracking_number: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # First time the status became delivered or returned. Kept forever; a later move does not
    # replace it. NULL when that change was never recorded.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last time a packing slip was printed. NULL until the first print. A reprint overwrites it.
    printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Business date for an offline order. NULL on online checkout and on rows
    # from before this column existed; those still count on created_at.
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when this process has claimed the new-order Telegram alert. NULL when
    # Telegram was off, and on every order placed before the column existed.
    telegram_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Claim for the customer message sent when the status first becomes confirmed
    # or shipped. NULL when that send was never claimed: the flag was off, the
    # phone was empty, or the order reached that status before this column existed.
    # A later edit does not clear it, so the same status is not sent again.
    customer_sms_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    customer_sms_shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inventory_held: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    user: Mapped[User | None] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.created_at",
    )


class OrderItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity >= 1 AND quantity <= 1000", name="quantity_in_range"),
        CheckConstraint("unit_price >= 0 AND line_total >= 0", name="money_non_negative"),
        CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0",
            name="unit_cost_non_negative",
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Variant sold on this line. SET NULL if the variant is later deleted; `sku`, `selection`
    # and `unit_price` below stay as the snapshot.
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    image_src: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)
    # Price snapshot at order time (hundredths of a percent). NULL on orders placed before
    # discounts were recorded.
    regular_price: Mapped[int | None] = mapped_column(Integer)
    base_discount: Mapped[int | None] = mapped_column(Integer)
    quantity_discount: Mapped[int | None] = mapped_column(Integer)
    total_discount: Mapped[int | None] = mapped_column(Integer)
    # Product cost_price at order time. NULL when the product had no cost, and on
    # lines placed before this column existed. Later cost edits do not change it.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    selection: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()


class OrderIdempotency(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The same key from the same shopper returns the original order."""

    __tablename__ = "order_idempotency"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_order_idempotency_key"),)

    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    order: Mapped[Order] = relationship()


class OrderActivity(UUIDPrimaryKeyMixin, Base):
    """Who changed an order, and what changed. Rows are inserted, never updated."""

    __tablename__ = "order_activities"
    __table_args__ = (
        CheckConstraint(
            "action IN ('created', 'status_changed', 'call_status_changed', "
            "'items_edited', 'courier_edited', 'printed', 'note_changed', "
            "'customer_message', 'payment_updated', 'courier_booked', "
            "'courier_webhook', 'return_requested')",
            name="action_known",
        ),
        Index("ix_order_activities_order_id_created_at", "order_id", "created_at"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
