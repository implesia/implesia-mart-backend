from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductCategory(StrEnum):
    GADGETS = "gadgets"
    FASHION = "fashion"


class StockStatus(StrEnum):
    AVAILABLE = "available"
    SOLD_OUT = "sold-out"
    COMING_SOON = "coming-soon"


class ProductBadge(StrEnum):
    NEW = "New"
    BEST_SELLER = "Best Seller"
    LIMITED = "Limited"


class SpecGroup(StrEnum):
    FABRIC = "fabric"
    CONSTRUCTION = "construction"
    SIZING = "sizing"
    CUSTOMIZATION = "customization"
    CARE = "care"
    TIMELINE = "timeline"
    POWER = "power"
    CONNECTIVITY = "connectivity"
    FEATURES = "features"
    BUILD = "build"
    DIMENSIONS = "dimensions"
    GENERAL = "general"


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Storefront catalog row.

    Card columns stay queryable. The long product-page copy lives in `content`
    and is loaded only for detail reads.
    """

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= price",
            name="compare_at_gte_price",
        ),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("category IN ('gadgets', 'fashion')", name="category_known"),
        CheckConstraint(
            "status IN ('available', 'sold-out', 'coming-soon')",
            name="status_known",
        ),
        CheckConstraint(
            "badge IS NULL OR badge IN ('New', 'Best Seller', 'Limited')",
            name="badge_known",
        ),
        Index(conv("ix_products_storefront"), "published", "category", "status", "price"),
        Index(conv("ix_products_featured"), "published", "featured"),
        Index(conv("ix_products_sort_order"), "sort_order"),
        Index(conv("ix_products_created_at"), "created_at"),
    )

    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    compare_at_price: Mapped[int | None] = mapped_column(Integer)
    # Null means made to order. Never returned on the public API.
    quantity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    badge: Mapped[str | None] = mapped_column(String(32))
    image_src: Mapped[str] = mapped_column(
        String(2048), nullable=False, default="", server_default=""
    )
    image_alt: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    unit_label: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", server_default=""
    )
    featured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    content: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Product {self.slug}>"
