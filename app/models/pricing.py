from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin


class PricingSettings(TimestampMixin, Base):
    """Store-wide discount rules. One row, id 1.

    Percentages are stored in hundredths of a percent (2800 = 28.00 %). `tiers` is a list of
    {"min_quantity": int, "extra": int} with `extra` in the same hundredths.
    """

    __tablename__ = "pricing_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("max_discount >= 0 AND max_discount <= 9999", name="max_discount_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tiers_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_discount: Mapped[int] = mapped_column(Integer, nullable=False)
    tiers: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
