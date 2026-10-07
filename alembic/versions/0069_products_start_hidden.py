"""new products start hidden

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.alter_column(
        "products",
        "published",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )
    op.execute(
        "UPDATE products SET published = false "
        "WHERE title IN ('Night upload check', 'Chiquita Mckay')"
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "published",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.true(),
    )
