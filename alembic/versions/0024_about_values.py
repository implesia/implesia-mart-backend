"""about page values

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "about_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("kicker", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_values")),
    )
    op.create_index(op.f("ix_about_values_slug"), "about_values", ["slug"], unique=True)
    op.create_table(
        "about_value_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("values_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["values_id"],
            ["about_values.id"],
            name=op.f("fk_about_value_items_values_id_about_values"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_value_items")),
    )
    op.create_index(
        op.f("ix_about_value_items_values_id"),
        "about_value_items",
        ["values_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_about_value_items_values_id"), table_name="about_value_items")
    op.drop_table("about_value_items")
    op.drop_index(op.f("ix_about_values_slug"), table_name="about_values")
    op.drop_table("about_values")
