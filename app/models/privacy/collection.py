import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PrivacyCollection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton information-collection section on the privacy page."""

    __tablename__ = "privacy_collections"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    intro: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<PrivacyCollection {self.slug}>"


class PrivacyCollectionCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One information card in the privacy collection section."""

    __tablename__ = "privacy_collection_cards"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("privacy_collections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<PrivacyCollectionCard {self.sort_order}>"
