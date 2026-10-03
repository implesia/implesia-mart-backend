import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShippingBlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton shipping section on the shipping page."""

    __tablename__ = "shipping_blocks"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    intro: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    timelines_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ShippingBlock {self.slug}>"


class ShippingBlockCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One coverage card in the shipping section."""

    __tablename__ = "shipping_block_cards"

    block_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipping_blocks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    variant: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingBlockCard {self.sort_order}>"


class ShippingBlockTime(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One delivery time in the shipping section."""

    __tablename__ = "shipping_block_times"

    block_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipping_blocks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    value: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingBlockTime {self.sort_order}>"


class ShippingBlockNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One note in the shipping section."""

    __tablename__ = "shipping_block_notes"

    block_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipping_blocks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ShippingBlockNote {self.sort_order}>"
