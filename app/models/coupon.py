"""Store coupons and the redemption row each order keeps.

Codes are stored in uppercase. A unique index on lower(code) keeps them
case-insensitive even if a row is written outside the API. Money is whole
taka except the percent value, which keeps two decimal places.

`used_count` is not a column. It is the number of redemptions whose
`cancelled_at` is still NULL.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Coupon(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint(
            "discount_type IN ('percent', 'fixed')",
            name="discount_type_known",
        ),
        CheckConstraint("value >= 0", name="value_non_negative"),
        CheckConstraint(
            "discount_type <> 'percent' OR value <= 100",
            name="percent_at_most_100",
        ),
        CheckConstraint(
            "discount_type <> 'fixed' OR max_discount IS NULL",
            name="fixed_has_no_cap",
        ),
        CheckConstraint(
            "max_discount IS NULL OR max_discount >= 1",
            name="max_discount_positive",
        ),
        CheckConstraint(
            "min_order_amount IS NULL OR min_order_amount >= 1",
            name="min_order_positive",
        ),
        CheckConstraint(
            "usage_limit_total IS NULL OR usage_limit_total >= 1",
            name="total_limit_positive",
        ),
        CheckConstraint(
            "usage_limit_per_phone IS NULL OR usage_limit_per_phone >= 1",
            name="phone_limit_positive",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at >= starts_at",
            name="window_ordered",
        ),
        CheckConstraint("length(code) >= 3 AND length(code) <= 32", name="code_length"),
        Index("uq_coupons_code_lower", text("lower(code)"), unique=True),
    )

    # Always uppercase. Lookup also compares lower(code).
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    discount_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Percent: 0.00–100.00. Fixed: whole taka. 0 is allowed only with free delivery.
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Caps a percent coupon. NULL for a fixed coupon.
    max_discount: Mapped[int | None] = mapped_column(Integer)
    # Merchandise after the quantity discount, before this coupon and before delivery.
    min_order_amount: Mapped[int | None] = mapped_column(Integer)
    # Inclusive. NULL start means already started. NULL end means it does not expire.
    # Admin clocks that omit a timezone are Asia/Dhaka. Stored as timestamptz.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_limit_total: Mapped[int | None] = mapped_column(Integer)
    usage_limit_per_phone: Mapped[int | None] = mapped_column(Integer)
    first_order_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    free_delivery: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class CouponProduct(Base):
    """When any row exists, the discount covers only these products (and any categories)."""

    __tablename__ = "coupon_products"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coupons.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class CouponCategory(Base):
    """A listed category includes its descendants. Empty lists mean the whole cart."""

    __tablename__ = "coupon_categories"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coupons.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class CouponRedemption(UUIDPrimaryKeyMixin, Base):
    """One row per order. Cancelling the order sets cancelled_at and stops the count.

    A return does not cancel the row: the discount was already given.
    """

    __tablename__ = "coupon_redemptions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'cancelled')", name="status_known"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint(
            "(status = 'active' AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL)",
            name="cancel_matches_status",
        ),
        Index("ix_coupon_redemptions_coupon_phone", "coupon_id", "phone"),
        Index("ix_coupon_redemptions_created_at", "created_at"),
    )

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coupons.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Same 01XXXXXXXXX form orders store.
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
