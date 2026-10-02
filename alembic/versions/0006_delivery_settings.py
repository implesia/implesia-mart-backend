"""store delivery rates

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delivery_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inside_dhaka", sa.Integer(), nullable=False),
        sa.Column("outside_dhaka", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_delivery_settings_singleton"),
        sa.CheckConstraint(
            "inside_dhaka >= 0 AND outside_dhaka >= 0",
            name="ck_delivery_settings_fees_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO delivery_settings "
            "(id, inside_dhaka, outside_dhaka, created_at, updated_at) "
            "VALUES (1, 70, 70, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_table("delivery_settings")
