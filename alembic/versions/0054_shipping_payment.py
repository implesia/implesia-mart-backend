"""shipping payment

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipping_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("intro", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_payments")),
    )
    op.create_index(op.f("ix_shipping_payments_slug"), "shipping_payments", ["slug"], unique=True)
    op.create_table(
        "shipping_payment_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("badge", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=800), nullable=False),
        sa.Column("footnote", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["shipping_payments.id"],
            name=op.f("fk_shipping_payment_cards_payment_id_shipping_payments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_payment_cards")),
    )
    op.create_index(
        op.f("ix_shipping_payment_cards_payment_id"),
        "shipping_payment_cards",
        ["payment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shipping_payment_cards_payment_id"), table_name="shipping_payment_cards")
    op.drop_table("shipping_payment_cards")
    op.drop_index(op.f("ix_shipping_payments_slug"), table_name="shipping_payments")
    op.drop_table("shipping_payments")
