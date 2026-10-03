import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomeCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every tile does not recreate the defaults."""

    __tablename__ = "home_categories"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    heading: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<HomeCategory {self.slug}>"


class HomeCategoryTile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One tile in the category grid on the home page."""

    __tablename__ = "home_category_tiles"

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    href: Mapped[str] = mapped_column(String(255), nullable=False)
    image_src: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<HomeCategoryTile {self.label}>"
