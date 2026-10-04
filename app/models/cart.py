import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.product import Product
from app.models.user import User


class Cart(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One open cart for a logged-in account, or for an anonymous shopper.

    The anonymous secret is never stored. ``guest_token_hash`` is the SHA-256
    of the token the browser keeps. Price is never stored on the cart.

    Unused guest carts are not removed yet. A later job deletes rows whose
    ``guest_token_hash`` is set and whose ``updated_at`` is past a threshold.
    Logged-in carts stay.
    """

    __tablename__ = "carts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_carts_user_id"),
        UniqueConstraint("guest_token_hash", name="uq_carts_guest_token_hash"),
        CheckConstraint(
            "(user_id IS NOT NULL AND guest_token_hash IS NULL) "
            "OR (user_id IS NULL AND guest_token_hash IS NOT NULL)",
            name="owner_kind",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    guest_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User | None] = relationship()
    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartItem.created_at",
    )


class CartItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        CheckConstraint("quantity >= 1 AND quantity <= 5", name="quantity_in_range"),
    )

    cart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    selection: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
