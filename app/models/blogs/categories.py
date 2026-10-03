import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BlogCategories(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton filter list for the blog page."""

    __tablename__ = "blog_categories"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<BlogCategories {self.slug}>"


class BlogCategoryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One filter chip on the blog list."""

    __tablename__ = "blog_category_items"

    categories_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blog_categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<BlogCategoryItem {self.sort_order}>"
