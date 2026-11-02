"""product drafts: a draft may be saved before a category is chosen

Revision ID: 0085
Revises: 0084
Create Date: 2026-11-02

Product status is the existing `products.published` flag: false = Draft (admin only),
true = Published (on the storefront). A draft needs only its name, so this makes
`products.category_id` nullable. Publishing still requires a category (enforced by the API).

What this does to existing data: nothing. Every existing row keeps its category and its
published flag (published rows stay Published, unpublished rows show as Draft).

Rollback limits (downgrade): makes `category_id` NOT NULL again. It refuses to run while any
draft has no category, so no row is changed or deleted; give those drafts a category (or
delete them) first.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("products", "category_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    missing = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM products WHERE category_id IS NULL")
    )
    if missing:
        raise RuntimeError(
            f"{missing} draft product(s) have no category. Assign one before downgrading."
        )
    op.alter_column("products", "category_id", existing_type=sa.Uuid(), nullable=False)
