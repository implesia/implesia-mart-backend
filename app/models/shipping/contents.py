from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShippingContents(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton sidebar heading on the shipping page."""

    __tablename__ = "shipping_contents"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ShippingContents {self.slug}>"
