import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomeFaq(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every question does not recreate the defaults."""

    __tablename__ = "home_faqs"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    kicker: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    more_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    more_href: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<HomeFaq {self.slug}>"


class HomeFaqItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question in the home FAQ."""

    __tablename__ = "home_faq_items"

    faq_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_faqs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    question: Mapped[str] = mapped_column(String(240), nullable=False)
    answer: Mapped[str] = mapped_column(String(2000), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<HomeFaqItem {self.question}>"
