from typing import Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class SiteFooter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The storefront footer. One row; with no row the built-in defaults are served.

    Link lists are JSON because an editor replaces them as one ordered unit (title, links,
    enabled flags, order). They are validated on write and re-validated on read.
    """

    __tablename__ = "site_footer"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    brand_name: Mapped[str] = mapped_column(
        String(80), nullable=False, default="", server_default=""
    )
    description: Mapped[str] = mapped_column(
        String(400), nullable=False, default="", server_default=""
    )
    logo_src: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    logo_alt: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    address: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    copyright_text: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default=""
    )
    show_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    show_social: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    show_whatsapp_cta: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sections: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON, nullable=False, default=list, server_default="[]"
    )
    trust_points: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON, nullable=False, default=list, server_default="[]"
    )
    legal_links: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON, nullable=False, default=list, server_default="[]"
    )

    def __repr__(self) -> str:
        return f"<SiteFooter {self.slug}>"
