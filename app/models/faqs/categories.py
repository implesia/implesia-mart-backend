import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FaqCategories(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton sidebar of topics on the FAQ page."""

    __tablename__ = "faq_categories"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    all_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    all_icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<FaqCategories {self.slug}>"


class FaqCategoryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One topic in the FAQ sidebar."""

    __tablename__ = "faq_category_items"

    categories_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("faq_categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<FaqCategoryItem {self.sort_order}>"
