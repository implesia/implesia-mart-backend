from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomePopup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Scroll-triggered promotional popup modal controlled from Admin CMS."""

    __tablename__ = "home_popup"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    badge_text: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", server_default=""
    )
    heading: Mapped[str] = mapped_column(
        String(140), nullable=False, default="", server_default=""
    )
    body: Mapped[str] = mapped_column(String(400), nullable=False, default="", server_default="")
    coupon_code: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", server_default=""
    )
    cta_label: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", server_default=""
    )
    cta_href: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    image_src: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    image_alt: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default=""
    )
    delay_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4, server_default="4"
    )
    min_scroll_px: Mapped[int] = mapped_column(
        Integer, nullable=False, default=150, server_default="150"
    )
    dismiss_cooldown_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default="24"
    )
    show_on_all_pages: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<HomePopup {self.slug}>"
