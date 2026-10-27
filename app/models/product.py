import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


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
        CheckConstraint(
            "status IN ('available', 'sold-out', 'coming-soon')",
            name="status_known",
        ),
        CheckConstraint(
            "badge IS NULL OR badge IN ('New', 'Best Seller', 'Limited')",
            name="badge_known",
        ),
        CheckConstraint(
            "min_order_quantity >= 1 AND min_order_quantity <= 5", name="min_qty_range"
        ),
        CheckConstraint(
            "max_order_quantity IS NULL OR "
            "(max_order_quantity >= min_order_quantity AND max_order_quantity <= 5)",
            name="max_qty_range",
        ),
        Index(conv("ix_products_storefront"), "published", "category", "status", "price"),
        Index(
            conv("ix_products_category_storefront"), "category_id", "published", "status", "price"
        ),
        Index(conv("ix_products_featured"), "published", "featured"),
        Index(conv("ix_products_sort_order"), "sort_order"),
        Index(conv("ix_products_created_at"), "created_at"),
    )

    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    # Primary category. Every product sits in exactly one node of the tree (any level).
    # RESTRICT: a category that still holds products cannot be deleted.
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    # Deprecated: the pre-0075 enum column. Kept (nullable, no CHECK) for one release so a
    # rollback or a reader of the raw table still works; nothing writes it any more.
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    # True when the product sells through `product_variants`. Then price, compare_at_price and
    # quantity above are a roll-up of the active variants (see variant_service.rollup), so
    # sorting, filtering and dashboards keep reading one column.
    has_variants: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # Per-order limits for this product. The platform cap of 5 still applies.
    min_order_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    max_order_quantity: Mapped[int | None] = mapped_column(Integer)
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


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One purchasable combination of a product's option values, with its own price and stock.

    `options` maps option group id to option value id (from `products.content.options`).
    `option_key` is the same mapping as a canonical string so the database itself refuses a
    duplicate combination. Stock `quantity` NULL means made to order.
    """

    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "option_key", name="uq_product_variants_option_key"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= price", name="compare_at_gte_price"
        ),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
        Index(
            conv("uq_product_variants_sku"),
            text("lower(sku)"),
            unique=True,
            postgresql_where=text("sku <> ''"),
            sqlite_where=text("sku <> ''"),
        ),
        Index(conv("ix_product_variants_product"), "product_id", "sort_order"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    options: Mapped[dict[str, str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    option_key: Mapped[str] = mapped_column(String(400), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    compare_at_price: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<ProductVariant {self.product_id} {self.option_key}>"
