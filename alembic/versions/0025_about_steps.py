"""about page order steps

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "about_steps",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_steps")),
    )
    op.create_index(op.f("ix_about_steps_slug"), "about_steps", ["slug"], unique=True)
    op.create_table(
        "about_step_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("steps_id", sa.Uuid(), nullable=False),
        sa.Column("step_label", sa.String(length=20), nullable=False),
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
            ["steps_id"],
            ["about_steps.id"],
            name=op.f("fk_about_step_items_steps_id_about_steps"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_step_items")),
    )
    op.create_index(
        op.f("ix_about_step_items_steps_id"),
        "about_step_items",
        ["steps_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_about_step_items_steps_id"), table_name="about_step_items")
    op.drop_table("about_step_items")
    op.drop_index(op.f("ix_about_steps_slug"), table_name="about_steps")
    op.drop_table("about_steps")
