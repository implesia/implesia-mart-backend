"""Add dynamic suburban_places JSON column to delivery_settings.

Revision ID: 0116
Revises: 0115
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0116"
down_revision: str | None = "0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("delivery_settings", sa.Column("suburban_places", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("delivery_settings", "suburban_places")
