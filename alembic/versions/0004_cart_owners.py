"""cart owners: logged-in accounts and anonymous shoppers

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("carts", "user_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("carts", sa.Column("guest_token_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_carts_guest_token_hash", "carts", ["guest_token_hash"])
    op.create_check_constraint(
        "ck_carts_owner_kind",
        "carts",
        "(user_id IS NOT NULL AND guest_token_hash IS NULL) "
        "OR (user_id IS NULL AND guest_token_hash IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM carts WHERE user_id IS NULL")
    op.drop_constraint("ck_carts_owner_kind", "carts", type_="check")
    op.drop_constraint("uq_carts_guest_token_hash", "carts", type_="unique")
    op.drop_column("carts", "guest_token_hash")
    op.alter_column("carts", "user_id", existing_type=sa.Uuid(), nullable=False)
