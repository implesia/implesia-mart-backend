"""shipping refund

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipping_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("note", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_refunds")),
    )
    op.create_index(op.f("ix_shipping_refunds_slug"), "shipping_refunds", ["slug"], unique=True)
    op.create_table(
        "shipping_refund_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("refund_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=800), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["refund_id"],
            ["shipping_refunds.id"],
            name=op.f("fk_shipping_refund_steps_refund_id_shipping_refunds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_refund_steps")),
    )
    op.create_index(
        op.f("ix_shipping_refund_steps_refund_id"),
        "shipping_refund_steps",
        ["refund_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shipping_refund_steps_refund_id"), table_name="shipping_refund_steps")
    op.drop_table("shipping_refund_steps")
    op.drop_index(op.f("ix_shipping_refunds_slug"), table_name="shipping_refunds")
    op.drop_table("shipping_refunds")
