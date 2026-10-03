import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AboutHero(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton banner at the top of the about page."""

    __tablename__ = "about_heroes"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    primary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    primary_href: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    secondary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    secondary_href: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<AboutHero {self.slug}>"


class AboutHeroImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One photo on the right side of the about hero. At most two."""

    __tablename__ = "about_hero_images"

    hero_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_heroes.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    src: Mapped[str] = mapped_column(String(255), nullable=False)
    alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutHeroImage {self.sort_order}>"
