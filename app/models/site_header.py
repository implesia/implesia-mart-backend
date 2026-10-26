from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class SiteHeader(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The storefront top navigation. One row; with no row the built-in menu is served.

    The links are one ordered JSON list (label, href, enabled) because an editor replaces the
    whole menu as a unit. They are validated on write and re-validated on read.
    """

    __tablename__ = "site_header"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON, nullable=False, default=list, server_default="[]"
    )

    def __repr__(self) -> str:
        return f"<SiteHeader {self.slug}>"
