import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShippingRefund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton refund section on the shipping page."""

    __tablename__ = "shipping_refunds"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    note: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ShippingRefund {self.slug}>"


class ShippingRefundStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One numbered step in the refund section."""

    __tablename__ = "shipping_refund_steps"

    refund_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipping_refunds.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingRefundStep {self.sort_order}>"
