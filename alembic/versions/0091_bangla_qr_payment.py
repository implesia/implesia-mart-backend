"""Bangla QR payment: payment settings (QR image) and the advance split on orders

Revision ID: 0091
Revises: 0090
Create Date: 2026-11-03

Creates `payment_settings` (one row, slug "main", holds the Bangla QR image path) and adds
the Bangla QR fields to `orders`:
 * `advance_percent` (NULL, or 25/50/75/100), `advance_amount` (default 0),
   `due_amount` (NULL = order placed before this; due is the whole total),
   `payment_reference` (transaction ID or sender number, default '').
 * `payment_method` may now be 'cod' or 'bangla_qr' (the old CHECK allowed only 'cod').

Safe by construction:
 * Additive only. No row is updated or deleted; existing orders keep payment_method 'cod',
   get advance_amount 0 and NULL for advance_percent / due_amount.
 * No settings row is seeded: with no QR the storefront hides the QR card and the checkout
   method, and the API refuses 'bangla_qr' orders, so nothing changes until an admin uploads
   a QR.

Rollback limits (downgrade): refuses to run while any order uses 'bangla_qr' (the old CHECK
would fail); otherwise drops the new columns and the `payment_settings` table. The QR file
in media/payment stays.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_COD_CHECK = "ck_orders_ck_orders_payment_cod"


def upgrade() -> None:
    op.create_table(
        "payment_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("bangla_qr_src", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_settings")),
    )
    op.create_index(op.f("ix_payment_settings_slug"), "payment_settings", ["slug"], unique=True)

    op.add_column("orders", sa.Column("advance_percent", sa.Integer(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("advance_amount", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("orders", sa.Column("due_amount", sa.Integer(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("payment_reference", sa.String(length=64), nullable=False, server_default=""),
    )
    # 0005 named it "ck_orders_payment_cod" without op.f, so the convention prefixed it again.
    op.drop_constraint(op.f(_OLD_COD_CHECK), "orders", type_="check")
    op.create_check_constraint(
        op.f("ck_orders_payment_known"), "orders", "payment_method IN ('cod', 'bangla_qr')"
    )
    op.create_check_constraint(
        op.f("ck_orders_advance_percent_known"),
        "orders",
        "advance_percent IS NULL OR advance_percent IN (25, 50, 75, 100)",
    )
    op.create_check_constraint(
        op.f("ck_orders_advance_non_negative"),
        "orders",
        "advance_amount >= 0 AND (due_amount IS NULL OR due_amount >= 0)",
    )


def downgrade() -> None:
    used = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM orders WHERE payment_method = 'bangla_qr'")
    )
    if used:
        raise RuntimeError(
            f"{used} order(s) use Bangla QR; downgrading would break the payment CHECK."
        )
    op.drop_constraint(op.f("ck_orders_advance_non_negative"), "orders", type_="check")
    op.drop_constraint(op.f("ck_orders_advance_percent_known"), "orders", type_="check")
    op.drop_constraint(op.f("ck_orders_payment_known"), "orders", type_="check")
    op.create_check_constraint(op.f(_OLD_COD_CHECK), "orders", "payment_method = 'cod'")
    op.drop_column("orders", "payment_reference")
    op.drop_column("orders", "due_amount")
    op.drop_column("orders", "advance_amount")
    op.drop_column("orders", "advance_percent")
    op.drop_index(op.f("ix_payment_settings_slug"), table_name="payment_settings")
    op.drop_table("payment_settings")
