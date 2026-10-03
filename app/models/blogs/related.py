from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BlogRelated(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton labels around contents, mentioned products, and more articles."""

    __tablename__ = "blog_related"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    toc_title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    products_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    products_subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    posts_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    posts_subtitle: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    posts_link_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    coming_soon_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    view_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    details_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<BlogRelated {self.slug}>"
