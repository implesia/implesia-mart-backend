from sqlalchemy import JSON, Boolean, CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DeliverySettings(TimestampMixin, Base):
    """City, Dhaka-suburban, and outside-Dhaka cash-on-delivery rates. One row, id 1."""

    __tablename__ = "delivery_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            "inside_dhaka >= 0 AND dhaka_suburban >= 0 AND outside_dhaka >= 0",
            name="fees_non_negative",
        ),
        CheckConstraint(
            "base_weight_grams >= 1 AND extra_weight_step_grams >= 1",
            name="weight_steps_positive",
        ),
        CheckConstraint(
            "extra_fee_inside >= 0 AND extra_fee_suburban >= 0 AND extra_fee_outside >= 0 "
            "AND packaging_weight_grams >= 0 AND default_product_weight_grams >= 0",
            name="extra_fees_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inside_dhaka: Mapped[int] = mapped_column(Integer, nullable=False)
    dhaka_suburban: Mapped[int] = mapped_column(Integer, nullable=False)
    outside_dhaka: Mapped[int] = mapped_column(Integer, nullable=False)
    inside_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    suburban_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    outside_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight_pricing_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    base_weight_grams: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000, server_default="1000"
    )
    extra_weight_step_grams: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000, server_default="1000"
    )
    extra_fee_inside: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    extra_fee_suburban: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    extra_fee_outside: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    packaging_weight_grams: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    default_product_weight_grams: Mapped[int] = mapped_column(
        Integer, nullable=False, default=500, server_default="500"
    )
    suburban_places: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
