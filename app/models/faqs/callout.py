from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FaqCallout(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton note above the FAQ list."""

    __tablename__ = "faq_callouts"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<FaqCallout {self.slug}>"
