import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShippingFaq(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton short FAQ on the shipping page."""

    __tablename__ = "shipping_faqs"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    more_before: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    more_link_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    more_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    more_after: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ShippingFaq {self.slug}>"


class ShippingFaqItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question in the shipping FAQ."""

    __tablename__ = "shipping_faq_items"

    faq_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("shipping_faqs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    answer: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingFaqItem {self.sort_order}>"
