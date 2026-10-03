import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShippingReturns(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton returns section on the shipping page."""

    __tablename__ = "shipping_returns"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    eligibility_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    eligibility_body: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ShippingReturns {self.slug}>"


class ShippingReturnRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One eligibility rule in the returns section."""

    __tablename__ = "shipping_return_rules"

    returns_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipping_returns.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingReturnRule {self.sort_order}>"


class ShippingReturnNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One special note in the returns section."""

    __tablename__ = "shipping_return_notes"

    returns_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipping_returns.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingReturnNote {self.sort_order}>"
