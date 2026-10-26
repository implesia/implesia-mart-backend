"""index the foreign keys that had no index

Revision ID: 0081
Revises: 0080
Create Date: 2026-10-26

Adds a plain b-tree index on seven foreign-key columns that nothing indexed:
`cart_items.product_id`, `cart_items.variant_id`, `order_items.product_id`,
`order_items.variant_id`, `orders.user_id`, `order_idempotency.order_id` and
`inquiries.handled_by_id`.

Why: deleting a product, variant, user or order makes Postgres look for referencing rows
(for CASCADE / SET NULL). Without an index on the child column that is a sequential scan of
the whole child table on every such delete.

Safe by construction:
 * Additive only: no column, constraint or row changes. Reads and writes behave the same.
 * `IF NOT EXISTS`, so re-running (or a database that already has an index with that
   name) is a no-op.
 * A plain `CREATE INDEX` takes a short write lock on the table while it builds. These
   tables are small for this store; on a large table build the index with
   `CREATE INDEX CONCURRENTLY` by hand first (the `IF NOT EXISTS` here then skips it).

Rollback limits (downgrade): drops the seven indexes (`IF EXISTS`). No data is lost; only
the delete-time lookups become sequential scans again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES: tuple[tuple[str, str], ...] = (
    ("cart_items", "product_id"),
    ("cart_items", "variant_id"),
    ("order_items", "product_id"),
    ("order_items", "variant_id"),
    ("orders", "user_id"),
    ("order_idempotency", "order_id"),
    ("inquiries", "handled_by_id"),
)


def upgrade() -> None:
    for table, column in _INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column], if_not_exists=True)


def downgrade() -> None:
    for table, column in _INDEXES:
        op.drop_index(f"ix_{table}_{column}", table_name=table, if_exists=True)
