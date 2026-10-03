"""shipping block

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _parent() -> None:
    op.create_table(
        "shipping_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("intro", sa.String(length=800), nullable=False),
        sa.Column("timelines_title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_blocks")),
    )
    op.create_index(op.f("ix_shipping_blocks_slug"), "shipping_blocks", ["slug"], unique=True)


def _child(table: str, columns: list[sa.Column]) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=False),
        *columns,
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["shipping_blocks.id"],
            name=op.f(f"fk_{table}_block_id_shipping_blocks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index(op.f(f"ix_{table}_block_id"), table, ["block_id"], unique=False)


def upgrade() -> None:
    _parent()
    _child(
        "shipping_block_cards",
        [
            sa.Column("icon", sa.String(length=40), nullable=False),
            sa.Column("eyebrow", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.String(length=800), nullable=False),
            sa.Column("variant", sa.String(length=20), nullable=False),
        ],
    )
    _child(
        "shipping_block_times",
        [
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("value", sa.String(length=80), nullable=False),
        ],
    )
    _child(
        "shipping_block_notes",
        [
            sa.Column("icon", sa.String(length=40), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.String(length=800), nullable=False),
        ],
    )


def downgrade() -> None:
    for table in ("shipping_block_notes", "shipping_block_times", "shipping_block_cards"):
        op.drop_index(op.f(f"ix_{table}_block_id"), table_name=table)
        op.drop_table(table)
    op.drop_index(op.f("ix_shipping_blocks_slug"), table_name="shipping_blocks")
    op.drop_table("shipping_blocks")
