import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AboutMissionSection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so the two cards are seeded once."""

    __tablename__ = "about_mission_sections"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)

    def __repr__(self) -> str:
        return f"<AboutMissionSection {self.slug}>"


class AboutMissionCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Vision or mission card on the about page."""

    __tablename__ = "about_mission_cards"
    __table_args__ = (UniqueConstraint("section_id", "card_key", name="uq_about_mission_card_key"),)

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_mission_sections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    card_key: Mapped[str] = mapped_column(String(20), nullable=False)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="verified")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(800), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutMissionCard {self.card_key}>"
