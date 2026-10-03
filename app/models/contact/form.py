from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContactForm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton message form on the contact page."""

    __tablename__ = "contact_forms"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    cta: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    hint: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    name_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    name_placeholder: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    phone_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    phone_placeholder: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subject_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    subject_placeholder: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    message_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    message_placeholder: Mapped[str] = mapped_column(String(160), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ContactForm {self.slug}>"
