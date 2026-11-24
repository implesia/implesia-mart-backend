"""cache courier fraud-check results by phone and provider

Revision ID: 0109
Revises: 0108
Create Date: 2026-11-24

Additive only. Creates courier_check_results. Does not update or delete
existing rows. Downgrade drops only this new table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0109"
down_revision: str | None = "0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    payload = (
        postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON()
    )
    op.create_table(
        "courier_check_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("payload", payload, nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courier_check_results")),
        sa.UniqueConstraint(
            "phone",
            "provider",
            name=op.f("uq_courier_check_results_phone_provider"),
        ),
    )


def downgrade() -> None:
    op.drop_table("courier_check_results")
