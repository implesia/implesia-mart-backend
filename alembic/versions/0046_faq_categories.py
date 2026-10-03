"""faq categories

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "faq_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("all_label", sa.String(length=80), nullable=False),
        sa.Column("all_icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_categories")),
    )
    op.create_index(op.f("ix_faq_categories_slug"), "faq_categories", ["slug"], unique=True)
    op.create_table(
        "faq_category_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("categories_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["categories_id"],
            ["faq_categories.id"],
            name=op.f("fk_faq_category_items_categories_id_faq_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_category_items")),
    )
    op.create_index(
        op.f("ix_faq_category_items_categories_id"),
        "faq_category_items",
        ["categories_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_faq_category_items_categories_id"), table_name="faq_category_items")
    op.drop_table("faq_category_items")
    op.drop_index(op.f("ix_faq_categories_slug"), table_name="faq_categories")
    op.drop_table("faq_categories")
