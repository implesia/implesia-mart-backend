"""sustainability page hero

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sustainability_heroes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("eyebrow", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=500), nullable=False),
        sa.Column("primary_label", sa.String(length=80), nullable=False),
        sa.Column("primary_href", sa.String(length=255), nullable=False),
        sa.Column("secondary_label", sa.String(length=80), nullable=False),
        sa.Column("secondary_href", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_heroes")),
    )
    op.create_index(
        op.f("ix_sustainability_heroes_slug"), "sustainability_heroes", ["slug"], unique=True
    )
    op.create_table(
        "sustainability_hero_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hero_id", sa.Uuid(), nullable=False),
        sa.Column("src", sa.String(length=255), nullable=False),
        sa.Column("alt", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["hero_id"],
            ["sustainability_heroes.id"],
            name=op.f("fk_sustainability_hero_images_hero_id_sustainability_heroes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_hero_images")),
    )
    op.create_index(
        op.f("ix_sustainability_hero_images_hero_id"),
        "sustainability_hero_images",
        ["hero_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sustainability_hero_images_hero_id"), table_name="sustainability_hero_images"
    )
    op.drop_table("sustainability_hero_images")
    op.drop_index(op.f("ix_sustainability_heroes_slug"), table_name="sustainability_heroes")
    op.drop_table("sustainability_heroes")
