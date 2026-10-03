import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AboutStorySection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every story does not recreate the default."""

    __tablename__ = "about_story_sections"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)

    def __repr__(self) -> str:
        return f"<AboutStorySection {self.slug}>"


class AboutStoryBlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One story block on the about page."""

    __tablename__ = "about_story_blocks"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_story_sections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kicker: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    cta_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    cta_href: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutStoryBlock {self.title}>"


class AboutStoryParagraph(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One paragraph inside a story block."""

    __tablename__ = "about_story_paragraphs"

    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_story_blocks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutStoryParagraph {self.sort_order}>"


class AboutStoryImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One photo beside a story. At most six."""

    __tablename__ = "about_story_images"

    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_story_blocks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    src: Mapped[str] = mapped_column(String(255), nullable=False)
    alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutStoryImage {self.sort_order}>"
