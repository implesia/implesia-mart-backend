import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomeFeatured(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so clearing the rail does not recreate the defaults."""

    __tablename__ = "home_featured"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    heading: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    view_all_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    view_all_href: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<HomeFeatured {self.slug}>"


class HomeFeaturedItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One product in the featured row on the home page."""

    __tablename__ = "home_featured_items"
    __table_args__ = (
        UniqueConstraint("featured_id", "product_id", name="uq_home_featured_product"),
    )

    featured_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_featured.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<HomeFeaturedItem {self.product_id}>"
