import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShippingPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton payment section on the shipping page."""

    __tablename__ = "shipping_payments"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    intro: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ShippingPayment {self.slug}>"


class ShippingPaymentCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One payment method card."""

    __tablename__ = "shipping_payment_cards"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipping_payments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    badge: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    footnote: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingPaymentCard {self.sort_order}>"
