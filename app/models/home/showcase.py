import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomeShowcase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so clearing a category row does not recreate its products."""

    __tablename__ = "home_showcase"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)

    def __repr__(self) -> str:
        return f"<HomeShowcase {self.slug}>"


class HomeShowcaseRow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One category row, gadgets or fashion, on the home page."""

    __tablename__ = "home_showcase_rows"
    __table_args__ = (UniqueConstraint("showcase_id", "key", name="uq_home_showcase_row_key"),)

    showcase_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_showcase.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    heading: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    href: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<HomeShowcaseRow {self.key}>"


class HomeShowcaseItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One product in a showcase row."""

    __tablename__ = "home_showcase_items"
    __table_args__ = (
        UniqueConstraint("row_id", "product_id", name="uq_home_showcase_row_product"),
    )

    row_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_showcase_rows.id", ondelete="CASCADE"),
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
        return f"<HomeShowcaseItem {self.product_id}>"
