from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BlogListing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton labels around the blog article list."""

    __tablename__ = "blog_listings"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    all_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    count_suffix: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    empty_message: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    featured_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    read_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    read_suffix: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    tabs_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<BlogListing {self.slug}>"
