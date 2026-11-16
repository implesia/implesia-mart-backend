from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SiteSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Storefront default SEO. One row (slug "main").

    A null field means the storefront keeps its built-in title, description,
    or title template. The API does not store a fallback string.
    """

    __tablename__ = "site_settings"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    seo_title: Mapped[str | None] = mapped_column(String(70), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(170), nullable=True)
    seo_title_template: Mapped[str | None] = mapped_column(String(80), nullable=True)

    def __repr__(self) -> str:
        return f"<SiteSettings {self.slug}>"
