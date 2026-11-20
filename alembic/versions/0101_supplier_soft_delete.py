"""Supplier soft delete

Revision ID: 0101
Revises: 0100
Create Date: 2026-11-20

Adds `is_deleted` and `deleted_at` to `suppliers`.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0101"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "suppliers",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "suppliers",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_suppliers_is_deleted", "suppliers", ["is_deleted"])


def downgrade() -> None:
    op.drop_index("ix_suppliers_is_deleted", table_name="suppliers")
    op.drop_column("suppliers", "deleted_at")
    op.drop_column("suppliers", "is_deleted")
