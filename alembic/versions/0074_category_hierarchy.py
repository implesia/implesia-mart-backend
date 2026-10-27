"""home categories: optional parent for nested subcategories

Revision ID: 0074
Revises: 0073
Create Date: 2026-10-17

Adds a nullable self-reference on home_category_tiles so a category can sit under
another one at any depth. Existing rows stay top-level (parent_id NULL).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "home_category_tiles",
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey(
                "home_category_tiles.id",
                ondelete="SET NULL",
                name="fk_home_category_tiles_parent_id",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_home_category_tiles_parent_id", "home_category_tiles", ["parent_id"])
    op.create_check_constraint(
        "ck_home_category_tiles_not_own_parent",
        "home_category_tiles",
        "parent_id IS NULL OR parent_id <> id",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_home_category_tiles_not_own_parent", "home_category_tiles", type_="check"
    )
    op.drop_index("ix_home_category_tiles_parent_id", table_name="home_category_tiles")
    op.drop_column("home_category_tiles", "parent_id")
