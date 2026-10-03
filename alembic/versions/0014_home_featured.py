"""home featured products

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_featured",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("heading", sa.String(length=120), nullable=False),
        sa.Column("view_all_label", sa.String(length=80), nullable=False),
        sa.Column("view_all_href", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_featured")),
    )
    op.create_index(op.f("ix_home_featured_slug"), "home_featured", ["slug"], unique=True)
    op.create_table(
        "home_featured_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("featured_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["featured_id"],
            ["home_featured.id"],
            name=op.f("fk_home_featured_items_featured_id_home_featured"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_home_featured_items_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_featured_items")),
        sa.UniqueConstraint("featured_id", "product_id", name="uq_home_featured_product"),
    )
    op.create_index(
        op.f("ix_home_featured_items_featured_id"),
        "home_featured_items",
        ["featured_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_home_featured_items_product_id"),
        "home_featured_items",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_home_featured_items_product_id"), table_name="home_featured_items")
    op.drop_index(op.f("ix_home_featured_items_featured_id"), table_name="home_featured_items")
    op.drop_table("home_featured_items")
    op.drop_index(op.f("ix_home_featured_slug"), table_name="home_featured")
    op.drop_table("home_featured")
