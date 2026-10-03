"""blog posts

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blog_posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("excerpt", sa.String(length=500), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("cover_image", sa.String(length=800), nullable=False),
        sa.Column("cover_alt", sa.String(length=200), nullable=False),
        sa.Column("author", sa.String(length=80), nullable=False),
        sa.Column("author_role", sa.String(length=80), nullable=False),
        sa.Column("published_at", sa.String(length=40), nullable=False),
        sa.Column("read_time", sa.String(length=40), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("related_product_slugs", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["blog_category_items.id"],
            name=op.f("fk_blog_posts_category_id_blog_category_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_posts")),
    )
    op.create_index(op.f("ix_blog_posts_slug"), "blog_posts", ["slug"], unique=True)
    op.create_index(op.f("ix_blog_posts_category_id"), "blog_posts", ["category_id"], unique=False)
    op.create_table(
        "blog_post_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("block_type", sa.String(length=20), nullable=False),
        sa.Column("text", sa.String(length=4000), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("variant", sa.String(length=20), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["blog_posts.id"],
            name=op.f("fk_blog_post_blocks_post_id_blog_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_post_blocks")),
    )
    op.create_index(
        op.f("ix_blog_post_blocks_post_id"),
        "blog_post_blocks",
        ["post_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_blog_post_blocks_post_id"), table_name="blog_post_blocks")
    op.drop_table("blog_post_blocks")
    op.drop_index(op.f("ix_blog_posts_category_id"), table_name="blog_posts")
    op.drop_index(op.f("ix_blog_posts_slug"), table_name="blog_posts")
    op.drop_table("blog_posts")
