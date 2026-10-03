"""blog categories

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blog_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_categories")),
    )
    op.create_index(op.f("ix_blog_categories_slug"), "blog_categories", ["slug"], unique=True)
    op.create_table(
        "blog_category_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("categories_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
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
            ["blog_categories.id"],
            name=op.f("fk_blog_category_items_categories_id_blog_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_category_items")),
    )
    op.create_index(
        op.f("ix_blog_category_items_categories_id"),
        "blog_category_items",
        ["categories_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_blog_category_items_categories_id"), table_name="blog_category_items")
    op.drop_table("blog_category_items")
    op.drop_index(op.f("ix_blog_categories_slug"), table_name="blog_categories")
    op.drop_table("blog_categories")
