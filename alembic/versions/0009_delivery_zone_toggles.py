"""delivery zone on/off switches

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "delivery_settings",
        sa.Column("inside_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("suburban_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("outside_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("delivery_settings", "outside_enabled")
    op.drop_column("delivery_settings", "suburban_enabled")
    op.drop_column("delivery_settings", "inside_enabled")
