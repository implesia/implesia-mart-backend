from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomePromo(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The slim promotional banner under Featured Products. One row; hidden until published."""

    __tablename__ = "home_promo"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    heading: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    body: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
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
    focal_x: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    focal_y: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    # "dark": light text over a dark scrim. "light": dark text over a light scrim.
    tone: Mapped[str] = mapped_column(
        String(10), nullable=False, default="dark", server_default="dark"
    )

    def __repr__(self) -> str:
        return f"<HomePromo {self.slug}>"
