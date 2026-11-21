"""index order_id foreign keys on customer_notifications and product_reviews

Revision ID: 0104
Revises: 0103
Create Date: 2026-11-21

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0104"
down_revision: str | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_customer_notifications_order_id",
        "customer_notifications",
        ["order_id"],
    )
    op.create_index(
        "ix_product_reviews_order_id",
        "product_reviews",
        ["order_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_reviews_order_id", table_name="product_reviews")
    op.drop_index("ix_customer_notifications_order_id", table_name="customer_notifications")
