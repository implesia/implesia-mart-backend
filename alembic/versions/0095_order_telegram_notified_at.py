"""Nullable claim time for the new-order Telegram alert

Revision ID: 0095
Revises: 0094
Create Date: 2026-11-10

Adds orders.telegram_notified_at (timestamptz, nullable). No existing row is
updated. Orders placed before this column, and orders placed while Telegram
is off, stay NULL.

ix_orders_created_at already exists (migration 0005). The new-order feed
filters and sorts on orders.created_at, so this revision does not add a
second index.

Downgrade drops only the new column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("telegram_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "telegram_notified_at")
