from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SiteContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The store's central contact settings. One row (slug "main").

    Header, footer, floating chat button, contact page, product WhatsApp button and the
    contact / about call-to-action links all read the phone, WhatsApp and email from here.
    Phone and WhatsApp are stored as local Bangladesh mobile numbers (01XXXXXXXXX); the
    `tel:` and `wa.me` links are derived from them, never stored.
    """

    __tablename__ = "site_contact"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(11), nullable=False)
    whatsapp: Mapped[str] = mapped_column(String(11), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)

    def __repr__(self) -> str:
        return f"<SiteContact {self.slug}>"
