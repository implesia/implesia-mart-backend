"""home showcase rows

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_showcase",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_showcase")),
    )
    op.create_index(op.f("ix_home_showcase_slug"), "home_showcase", ["slug"], unique=True)
    op.create_table(
        "home_showcase_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("showcase_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("heading", sa.String(length=120), nullable=False),
        sa.Column("href", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["showcase_id"],
            ["home_showcase.id"],
            name=op.f("fk_home_showcase_rows_showcase_id_home_showcase"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_showcase_rows")),
        sa.UniqueConstraint("showcase_id", "key", name="uq_home_showcase_row_key"),
    )
    op.create_index(
        op.f("ix_home_showcase_rows_showcase_id"),
        "home_showcase_rows",
        ["showcase_id"],
        unique=False,
    )
    op.create_table(
        "home_showcase_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("row_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_home_showcase_items_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["row_id"],
            ["home_showcase_rows.id"],
            name=op.f("fk_home_showcase_items_row_id_home_showcase_rows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_showcase_items")),
        sa.UniqueConstraint("row_id", "product_id", name="uq_home_showcase_row_product"),
    )
    op.create_index(
        op.f("ix_home_showcase_items_row_id"), "home_showcase_items", ["row_id"], unique=False
    )
    op.create_index(
        op.f("ix_home_showcase_items_product_id"),
        "home_showcase_items",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_home_showcase_items_product_id"), table_name="home_showcase_items")
    op.drop_index(op.f("ix_home_showcase_items_row_id"), table_name="home_showcase_items")
    op.drop_table("home_showcase_items")
    op.drop_index(op.f("ix_home_showcase_rows_showcase_id"), table_name="home_showcase_rows")
    op.drop_table("home_showcase_rows")
    op.drop_index(op.f("ix_home_showcase_slug"), table_name="home_showcase")
    op.drop_table("home_showcase")
