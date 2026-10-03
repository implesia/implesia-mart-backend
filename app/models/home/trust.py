import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomeTrust(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every benefit does not recreate the defaults."""

    __tablename__ = "home_trust"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)

    def __repr__(self) -> str:
        return f"<HomeTrust {self.slug}>"


class HomeTrustItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One link in the strip under the home hero."""

    __tablename__ = "home_trust_items"

    trust_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_trust.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    href: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<HomeTrustItem {self.label}>"
