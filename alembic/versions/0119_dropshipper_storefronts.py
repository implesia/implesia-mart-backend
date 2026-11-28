"""Phase 35: Additive multi-tenant dropshipper storefronts & imported product catalog.

Revision ID: 0119
Revises: 0118
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0119"
down_revision: str | None = "0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "dropshipper_stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dropshipper_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "template_id",
            sa.String(length=32),
            nullable=False,
            server_default="modern_tech",
        ),
        sa.Column("theme_config", _json_type(), nullable=False),
        sa.Column("brand_config", _json_type(), nullable=False),
        sa.Column("hero_config", _json_type(), nullable=False),
        sa.Column("sections_config", _json_type(), nullable=False),
        sa.Column("seo_title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("seo_description", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("seo_og_image_url", sa.String(length=500), nullable=True),
        sa.Column("google_site_verification", sa.String(length=120), nullable=True),
        sa.Column("bing_site_verification", sa.String(length=120), nullable=True),
        sa.Column("meta_pixel_id", sa.String(length=32), nullable=True),
        sa.Column("meta_capi_token", sa.String(length=512), nullable=True),
        sa.Column("meta_test_event_code", sa.String(length=64), nullable=True),
        sa.Column("gtm_id", sa.String(length=32), nullable=True),
        sa.Column("ga4_measurement_id", sa.String(length=32), nullable=True),
        sa.Column("tiktok_pixel_id", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dropshipper_stores")),
        sa.ForeignKeyConstraint(
            ["dropshipper_id"],
            ["users.id"],
            name=op.f("fk_dropshipper_stores_dropshipper_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["dropshipper_profiles.id"],
            name=op.f("fk_dropshipper_stores_profile_id_dropshipper_profiles"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("dropshipper_id", name=op.f("uq_dropshipper_stores_dropshipper_id")),
        sa.UniqueConstraint("profile_id", name=op.f("uq_dropshipper_stores_profile_id")),
        sa.UniqueConstraint("slug", name=op.f("uq_dropshipper_stores_slug")),
        sa.CheckConstraint(
            "template_id IN ('modern_tech', 'minimal_boutique', 'flash_deal')",
            name=op.f("ck_dropshipper_stores_template_id_known"),
        ),
    )
    op.create_index(
        op.f("ix_dropshipper_stores_slug"),
        "dropshipper_stores",
        ["slug"],
        unique=True,
    )
    op.create_index(
        op.f("ix_dropshipper_stores_is_published"),
        "dropshipper_stores",
        ["is_published"],
        unique=False,
    )

    op.create_table(
        "dropshipper_store_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("custom_title", sa.String(length=200), nullable=True),
        sa.Column("selling_price", sa.Integer(), nullable=False),
        sa.Column("compare_at_price", sa.Integer(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dropshipper_store_products")),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["dropshipper_stores.id"],
            name=op.f("fk_dropshipper_store_products_store_id_dropshipper_stores"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_dropshipper_store_products_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "store_id",
            "product_id",
            name=op.f("uq_dropshipper_store_products_store_product"),
        ),
        sa.CheckConstraint(
            "selling_price >= 0",
            name=op.f("ck_dropshipper_store_products_selling_price_non_negative"),
        ),
        sa.CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= 0",
            name=op.f("ck_dropshipper_store_products_compare_at_non_negative"),
        ),
    )
    op.create_index(
        op.f("ix_dropshipper_store_products_store_id"),
        "dropshipper_store_products",
        ["store_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dropshipper_store_products_product_id"),
        "dropshipper_store_products",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_dropshipper_store_products_product_id"),
        table_name="dropshipper_store_products",
    )
    op.drop_index(
        op.f("ix_dropshipper_store_products_store_id"),
        table_name="dropshipper_store_products",
    )
    op.drop_table("dropshipper_store_products")
    op.drop_index(op.f("ix_dropshipper_stores_is_published"), table_name="dropshipper_stores")
    op.drop_index(op.f("ix_dropshipper_stores_slug"), table_name="dropshipper_stores")
    op.drop_table("dropshipper_stores")
