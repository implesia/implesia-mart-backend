"""shipping returns

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipping_returns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("eligibility_title", sa.String(length=200), nullable=False),
        sa.Column("eligibility_body", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_returns")),
    )
    op.create_index(op.f("ix_shipping_returns_slug"), "shipping_returns", ["slug"], unique=True)
    op.create_table(
        "shipping_return_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("returns_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=400), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["returns_id"],
            ["shipping_returns.id"],
            name=op.f("fk_shipping_return_rules_returns_id_shipping_returns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_return_rules")),
    )
    op.create_index(
        op.f("ix_shipping_return_rules_returns_id"),
        "shipping_return_rules",
        ["returns_id"],
        unique=False,
    )
    op.create_table(
        "shipping_return_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("returns_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
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
            ["returns_id"],
            ["shipping_returns.id"],
            name=op.f("fk_shipping_return_notes_returns_id_shipping_returns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_return_notes")),
    )
    op.create_index(
        op.f("ix_shipping_return_notes_returns_id"),
        "shipping_return_notes",
        ["returns_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shipping_return_notes_returns_id"), table_name="shipping_return_notes")
    op.drop_table("shipping_return_notes")
    op.drop_index(op.f("ix_shipping_return_rules_returns_id"), table_name="shipping_return_rules")
    op.drop_table("shipping_return_rules")
    op.drop_index(op.f("ix_shipping_returns_slug"), table_name="shipping_returns")
    op.drop_table("shipping_returns")
