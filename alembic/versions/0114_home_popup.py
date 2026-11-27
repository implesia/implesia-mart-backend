"""Add home_popup table for scroll-triggered storefront promo popup.

Revision ID: 0114
Revises: 0113
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0114"
down_revision: str | None = "0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_popup",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("badge_text", sa.String(length=60), server_default="", nullable=False),
        sa.Column("heading", sa.String(length=140), server_default="", nullable=False),
        sa.Column("body", sa.String(length=400), server_default="", nullable=False),
        sa.Column("coupon_code", sa.String(length=40), server_default="", nullable=False),
        sa.Column("cta_label", sa.String(length=60), server_default="", nullable=False),
        sa.Column("cta_href", sa.String(length=255), server_default="", nullable=False),
        sa.Column("image_src", sa.String(length=255), server_default="", nullable=False),
        sa.Column("image_alt", sa.String(length=200), server_default="", nullable=False),
        sa.Column("delay_seconds", sa.Integer(), server_default="4", nullable=False),
        sa.Column("min_scroll_px", sa.Integer(), server_default="150", nullable=False),
        sa.Column("dismiss_cooldown_hours", sa.Integer(), server_default="24", nullable=False),
        sa.Column("show_on_all_pages", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_popup")),
    )
    op.create_index(op.f("ix_home_popup_slug"), "home_popup", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_home_popup_slug"), table_name="home_popup")
    op.drop_table("home_popup")
