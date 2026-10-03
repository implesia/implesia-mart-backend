"""home review screenshots

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_reviews",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_reviews")),
    )
    op.create_index(op.f("ix_home_reviews_slug"), "home_reviews", ["slug"], unique=True)
    op.create_table(
        "home_review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("product", sa.String(length=120), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("image_src", sa.String(length=255), nullable=False),
        sa.Column("image_alt", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["home_reviews.id"],
            name=op.f("fk_home_review_items_review_id_home_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_review_items")),
    )
    op.create_index(
        op.f("ix_home_review_items_review_id"),
        "home_review_items",
        ["review_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_home_review_items_review_id"), table_name="home_review_items")
    op.drop_table("home_review_items")
    op.drop_index(op.f("ix_home_reviews_slug"), table_name="home_reviews")
    op.drop_table("home_reviews")
