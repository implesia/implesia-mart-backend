"""product SEO fields and old-slug redirects

Revision ID: 0088
Revises: 0087
Create Date: 2026-11-02

Adds:
- `products.seo_title` (up to 120), `products.seo_description` (up to 320) and
  `products.seo_keywords` (up to 500, comma-separated). All default to "" (the storefront then
  falls back to the product title and a trimmed description).
- `product_slug_redirects`: slugs a product used before its slug was edited, so old links still
  reach the product. Rows go with their product (ON DELETE CASCADE).

What this does to existing data: nothing is rewritten. Existing products get empty SEO fields.

Rollback limits (downgrade): drops the three columns and the redirect table, so saved SEO text
and old-slug redirects are lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("seo_title", sa.String(length=120), server_default="", nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("seo_description", sa.String(length=320), server_default="", nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("seo_keywords", sa.String(length=500), server_default="", nullable=False),
    )
    op.create_table(
        "product_slug_redirects",
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_slug_redirects_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("slug", name=op.f("pk_product_slug_redirects")),
    )
    op.create_index(
        "ix_product_slug_redirects_product_id", "product_slug_redirects", ["product_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_product_slug_redirects_product_id", table_name="product_slug_redirects")
    op.drop_table("product_slug_redirects")
    op.drop_column("products", "seo_keywords")
    op.drop_column("products", "seo_description")
    op.drop_column("products", "seo_title")
