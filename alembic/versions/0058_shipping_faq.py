"""shipping faq

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipping_faqs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("more_before", sa.String(length=200), nullable=False),
        sa.Column("more_link_label", sa.String(length=80), nullable=False),
        sa.Column("more_href", sa.String(length=800), nullable=False),
        sa.Column("more_after", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_faqs")),
    )
    op.create_index(op.f("ix_shipping_faqs_slug"), "shipping_faqs", ["slug"], unique=True)
    op.create_table(
        "shipping_faq_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("faq_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(length=240), nullable=False),
        sa.Column("answer", sa.String(length=2000), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["faq_id"],
            ["shipping_faqs.id"],
            name=op.f("fk_shipping_faq_items_faq_id_shipping_faqs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_faq_items")),
    )
    op.create_index(
        op.f("ix_shipping_faq_items_faq_id"),
        "shipping_faq_items",
        ["faq_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shipping_faq_items_faq_id"), table_name="shipping_faq_items")
    op.drop_table("shipping_faq_items")
    op.drop_index(op.f("ix_shipping_faqs_slug"), table_name="shipping_faqs")
    op.drop_table("shipping_faqs")
