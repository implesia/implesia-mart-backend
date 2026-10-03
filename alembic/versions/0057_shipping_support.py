"""shipping support

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipping_supports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("primary_label", sa.String(length=80), nullable=False),
        sa.Column("primary_href", sa.String(length=800), nullable=False),
        sa.Column("secondary_label", sa.String(length=80), nullable=False),
        sa.Column("secondary_href", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_supports")),
    )
    op.create_index(op.f("ix_shipping_supports_slug"), "shipping_supports", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_shipping_supports_slug"), table_name="shipping_supports")
    op.drop_table("shipping_supports")
