"""home trust benefits

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_trust",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_trust")),
    )
    op.create_index(op.f("ix_home_trust_slug"), "home_trust", ["slug"], unique=True)
    op.create_table(
        "home_trust_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trust_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("href", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["trust_id"],
            ["home_trust.id"],
            name=op.f("fk_home_trust_items_trust_id_home_trust"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_trust_items")),
    )
    op.create_index(
        op.f("ix_home_trust_items_trust_id"), "home_trust_items", ["trust_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_home_trust_items_trust_id"), table_name="home_trust_items")
    op.drop_table("home_trust_items")
    op.drop_index(op.f("ix_home_trust_slug"), table_name="home_trust")
    op.drop_table("home_trust")
