import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BadgeTone(StrEnum):
    """Colour pairs the storefront already uses for chips. The frontend maps each one to its
    design-system classes, so a badge can never introduce an off-brand colour."""

    PRIMARY = "primary"
    GOLD = "gold"
    DARK = "dark"
    ALERT = "alert"
    SOFT = "soft"
    SOFT_GOLD = "soft-gold"


# Seeded by migration 0084 from the old fixed `products.badge` choices. Their slugs are what
# `products.badge` (ranking, the "new" view, the `badge` filter) is derived from.
SYSTEM_BADGES: dict[str, str] = {
    "best-seller": "Best Seller",
    "new": "New",
    "limited": "Limited",
}


class Badge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A product badge an admin can create, edit, switch off, and attach to products."""

    __tablename__ = "badges"
    __table_args__ = (
        CheckConstraint(
            "tone IN ('primary', 'gold', 'dark', 'alert', 'soft', 'soft-gold')",
            name="tone_known",
        ),
        Index(conv("uq_badges_name_lower"), text("lower(name)"), unique=True),
    )

    name: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    tone: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BadgeTone.PRIMARY.value, server_default="primary"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    # Built-in badges (New, Best Seller, Limited) drive catalog ranking; they cannot be deleted.
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    def __repr__(self) -> str:
        return f"<Badge {self.slug}>"


class ProductBadgeLink(Base):
    """Which badges a product shows, in the order the admin picked them.

    Deleting a product removes its links (CASCADE). Deleting a badge that is still linked is
    refused (RESTRICT); the service answers 409 and suggests switching it off instead.
    """

    __tablename__ = "product_badges"
    __table_args__ = (Index(conv("ix_product_badges_badge_id"), "badge_id"),)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    badge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("badges.id", ondelete="RESTRICT"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<ProductBadgeLink {self.product_id} {self.badge_id}>"
