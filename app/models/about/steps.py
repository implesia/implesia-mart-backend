import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AboutSteps(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every step does not recreate the defaults."""

    __tablename__ = "about_steps"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    kicker: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<AboutSteps {self.slug}>"


class AboutStepItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One numbered step in the about-page order process."""

    __tablename__ = "about_step_items"

    steps_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_steps.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    step_label: Mapped[str] = mapped_column(String(20), nullable=False)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="task_alt")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutStepItem {self.step_label}>"
