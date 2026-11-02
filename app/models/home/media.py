from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _text(length: int) -> Mapped[str]:
    return mapped_column(String(length), nullable=False, default="", server_default="")


class HomeMedia(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The video/media section above the testimonials. One row; hidden until published."""

    __tablename__ = "home_media"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    heading: Mapped[str] = _text(120)
    subheading: Mapped[str] = _text(240)
    # "image", "video" (uploaded MP4/WEBM) or "youtube". Only that type's fields are kept.
    media_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="image", server_default="image"
    )
    image_src: Mapped[str] = _text(255)
    video_src: Mapped[str] = _text(255)
    youtube_id: Mapped[str] = _text(20)
    # Poster for a video, or the click-to-play still for YouTube.
    thumbnail_src: Mapped[str] = _text(255)
    media_alt: Mapped[str] = _text(200)
    description: Mapped[str] = _text(500)
    cta_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    cta_label: Mapped[str] = _text(60)
    cta_href: Mapped[str] = _text(255)

    def __repr__(self) -> str:
        return f"<HomeMedia {self.slug}>"
