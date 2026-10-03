from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FaqListing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton count and empty-search copy on the FAQ page."""

    __tablename__ = "faq_listings"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    count_suffix: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    empty_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    empty_body: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<FaqListing {self.slug}>"
