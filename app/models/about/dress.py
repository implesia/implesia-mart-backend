import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AboutDressSection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every block does not recreate the default."""

    __tablename__ = "about_dress_sections"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)

    def __repr__(self) -> str:
        return f"<AboutDressSection {self.slug}>"


class AboutDressBlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One custom-dress block on the about page."""

    __tablename__ = "about_dress_blocks"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_dress_sections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kicker: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    primary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    primary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    secondary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    secondary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutDressBlock {self.title}>"


class AboutDressFeature(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One highlight inside a custom-dress block."""

    __tablename__ = "about_dress_features"

    dress_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_dress_blocks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="design_services")
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutDressFeature {self.title}>"


class AboutDressImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One photo on a custom-dress block. At most twelve."""

    __tablename__ = "about_dress_images"

    dress_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_dress_blocks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    src: Mapped[str] = mapped_column(String(255), nullable=False)
    alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutDressImage {self.sort_order}>"
