import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContactFaq(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton FAQ at the bottom of the contact page."""

    __tablename__ = "contact_faqs"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ContactFaq {self.slug}>"


class ContactFaqItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question on the contact FAQ."""

    __tablename__ = "contact_faq_items"

    faq_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_faqs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    answer: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ContactFaqItem {self.sort_order}>"
