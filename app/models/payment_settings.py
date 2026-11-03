from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store payment settings. One row (slug "main").

    `bangla_qr_src` is the one Bangla QR image the product page and checkout show. Empty
    means no QR: the product page card and the checkout "Bangla QR" method are hidden and
    the API refuses `bangla_qr` orders.
    """

    __tablename__ = "payment_settings"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    bangla_qr_src: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )

    def __repr__(self) -> str:
        return f"<PaymentSettings {self.slug}>"
