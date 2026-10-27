"""home promotional banner (one row, hidden by default)

Revision ID: 0079
Revises: 0078
Create Date: 2026-10-26

Creates `home_promo`, the content-managed slim banner shown under Featured Products.

Safe by construction:
 * Additive only: one new table. No existing table, column or row is touched.
 * No row is seeded. With no row the public endpoint returns null and the storefront shows
   no banner, so nothing is invented and nothing changes until an editor publishes one.
 * Every column has a server default (is_active false, focal point 50/50, tone dark).

Rollback limits (downgrade): drops `home_promo`, so a banner an editor configured after
upgrading is lost. Nothing else is affected. Files uploaded to media/promo stay on disk.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _text(name: str, length: int) -> sa.Column[str]:
    return sa.Column(name, sa.String(length=length), nullable=False, server_default="")


def upgrade() -> None:
    op.create_table(
        "home_promo",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        _text("eyebrow", 80),
        _text("heading", 120),
        _text("body", 200),
        _text("cta_label", 60),
        _text("cta_href", 255),
        _text("image_src", 255),
        _text("image_alt", 200),
        sa.Column("focal_x", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("focal_y", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("tone", sa.String(length=10), nullable=False, server_default="dark"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_promo")),
    )
    op.create_index(op.f("ix_home_promo_slug"), "home_promo", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_home_promo_slug"), table_name="home_promo")
    op.drop_table("home_promo")
