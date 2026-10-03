"""store a hero price line that is not a plain amount

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "home_banner_slides", sa.Column("price_text", sa.String(length=80), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("home_banner_slides", "price_text")
