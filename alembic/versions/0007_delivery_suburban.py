"""add dhaka suburban delivery rate

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "delivery_settings",
        sa.Column("dhaka_suburban", sa.Integer(), server_default="100", nullable=False),
    )
    op.execute(
        sa.text(
            "UPDATE delivery_settings "
            "SET outside_dhaka = 130 "
            "WHERE id = 1 AND inside_dhaka = 70 AND outside_dhaka = 70"
        )
    )
    op.drop_constraint(
        "ck_delivery_settings_fees_non_negative", "delivery_settings", type_="check"
    )
    op.create_check_constraint(
        "ck_delivery_settings_fees_non_negative",
        "delivery_settings",
        "inside_dhaka >= 0 AND dhaka_suburban >= 0 AND outside_dhaka >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_delivery_settings_fees_non_negative", "delivery_settings", type_="check"
    )
    op.create_check_constraint(
        "ck_delivery_settings_fees_non_negative",
        "delivery_settings",
        "inside_dhaka >= 0 AND outside_dhaka >= 0",
    )
    op.drop_column("delivery_settings", "dhaka_suburban")
