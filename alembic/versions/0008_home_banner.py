"""home page banner

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

banner_accent = sa.Enum("gold", "teal", "rose", "ink", name="banner_accent")


def upgrade() -> None:
    op.create_table(
        "home_banners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("brand_name", sa.String(length=80), nullable=False),
        sa.Column("aria_label", sa.String(length=120), nullable=False),
        sa.Column("trust_line", sa.String(length=200), nullable=False),
        sa.Column("previous_label", sa.String(length=80), nullable=False),
        sa.Column("next_label", sa.String(length=80), nullable=False),
        sa.Column("slide_label", sa.String(length=40), nullable=False),
        sa.Column("autoplay_delay_ms", sa.Integer(), nullable=False),
        sa.Column("transition_speed_ms", sa.Integer(), nullable=False),
        sa.Column("pause_on_hover", sa.Boolean(), nullable=False),
        sa.Column("loop", sa.Boolean(), nullable=False),
        sa.Column("keyboard_enabled", sa.Boolean(), nullable=False),
        sa.Column("disable_on_interaction", sa.Boolean(), nullable=False),
        sa.Column("cross_fade", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_banners")),
    )
    op.create_index(op.f("ix_home_banners_slug"), "home_banners", ["slug"], unique=True)

    op.create_table(
        "home_banner_slides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("banner_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("eyebrow", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("compare_at_price", sa.Integer(), nullable=True),
        sa.Column("price_prefix", sa.String(length=40), nullable=True),
        sa.Column("primary_cta_label", sa.String(length=80), nullable=False),
        sa.Column("primary_cta_href", sa.String(length=255), nullable=False),
        sa.Column("secondary_cta_label", sa.String(length=80), nullable=False),
        sa.Column("secondary_cta_href", sa.String(length=255), nullable=False),
        sa.Column("image_src", sa.String(length=255), nullable=False),
        sa.Column("image_alt", sa.String(length=200), nullable=False),
        sa.Column("accent", banner_accent, nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["banner_id"],
            ["home_banners.id"],
            name=op.f("fk_home_banner_slides_banner_id_home_banners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_banner_slides")),
    )
    op.create_index(
        op.f("ix_home_banner_slides_banner_id"), "home_banner_slides", ["banner_id"], unique=False
    )
    op.create_index(op.f("ix_home_banner_slides_slug"), "home_banner_slides", ["slug"], unique=True)
    op.create_index(
        op.f("ix_home_banner_slides_is_published"),
        "home_banner_slides",
        ["is_published"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_home_banner_slides_is_published"), table_name="home_banner_slides")
    op.drop_index(op.f("ix_home_banner_slides_slug"), table_name="home_banner_slides")
    op.drop_index(op.f("ix_home_banner_slides_banner_id"), table_name="home_banner_slides")
    op.drop_table("home_banner_slides")
    op.drop_index(op.f("ix_home_banners_slug"), table_name="home_banners")
    op.drop_table("home_banners")
    banner_accent.drop(op.get_bind(), checkfirst=True)
