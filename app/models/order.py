import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.product import Product
from app.models.user import User


class OrderStatus(StrEnum):
    NEW = "new"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class OrderSource(StrEnum):
    CART = "cart"
    DIRECT = "direct"


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A cash-on-delivery order. Money columns are a snapshot from the server."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("number", name="uq_orders_number"),
        CheckConstraint(
            "status IN ('new', 'confirmed', 'shipped', 'delivered', 'cancelled', 'returned')",
            name="status_known",
        ),
        CheckConstraint("source IN ('cart', 'direct')", name="source_known"),
        CheckConstraint(
            "subtotal >= 0 AND shipping >= 0 AND total >= 0", name="money_non_negative"
        ),
        CheckConstraint("payment_method = 'cod'", name="payment_cod"),
        Index("ix_orders_phone", "phone"),
        Index("ix_orders_created_at", "created_at"),
    )

    number: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OrderStatus.NEW.value)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, default="cod")
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
    courier_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    tracking_number: Mapped[str] = mapped_column(String(120), nullable=False, default="")
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
        CheckConstraint("quantity >= 1 AND quantity <= 5", name="quantity_in_range"),
        CheckConstraint("unit_price >= 0 AND line_total >= 0", name="money_non_negative"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    image_src: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()


class OrderIdempotency(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The same key from the same shopper returns the original order."""

    __tablename__ = "order_idempotency"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_order_idempotency_key"),)

    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )

    order: Mapped[Order] = relationship()
