from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BlogCta(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton closing banner on each blog article."""

    __tablename__ = "blog_ctas"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    primary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    primary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    secondary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    secondary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<BlogCta {self.slug}>"
