"""add template selector column to home_banners

Revision ID: 0113
Revises: 0112
Create Date: 2026-11-26

Additive-only:
* Adds `template` VARCHAR(32) NOT NULL DEFAULT 'classic' to `home_banners`
  with check constraint `ck_home_banners_template_known` allowing
  'classic' and 'image_only'.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0113"
down_revision: str | None = "0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEMPLATE_CHECK_SQL = "template IN ('classic', 'image_only')"


def upgrade() -> None:
    op.add_column(
        "home_banners",
        sa.Column(
            "template",
            sa.String(length=32),
            nullable=False,
            server_default="classic",
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(
            op.f("ck_home_banners_template_known"),
            "home_banners",
            _TEMPLATE_CHECK_SQL,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            op.f("ck_home_banners_template_known"),
            "home_banners",
            type_="check",
        )
    op.drop_column("home_banners", "template")
