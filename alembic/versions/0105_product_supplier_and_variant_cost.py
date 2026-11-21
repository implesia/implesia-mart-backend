"""add optional supplier_id on products, variant cost_price, and payment_updated activity

Revision ID: 0105
Revises: 0104
Create Date: 2026-11-21

Additive-only:
* products.supplier_id UUID NULL -> suppliers(id) ON DELETE SET NULL + ix_products_supplier_id
* product_variants.cost_price NUMERIC(12, 2) NULL + ck_product_variants_cost_price_non_negative
* Widens order_activities.action check to also allow 'payment_updated'.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0105"
down_revision: str | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ACTION_SQL = (
    "action IN ('created', 'status_changed', 'call_status_changed', "
    "'items_edited', 'courier_edited', 'printed', 'note_changed', "
    "'customer_message', 'payment_updated')"
)
_OLD_ACTION_SQL = (
    "action IN ('created', 'status_changed', 'call_status_changed', "
    "'items_edited', 'courier_edited', 'printed', 'note_changed', "
    "'customer_message')"
)


def _checks(table: str, needle: str) -> list[str]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "WHERE rel.relname = :table AND con.contype = 'c' "
                "AND pg_get_constraintdef(con.oid) ILIKE :needle"
            ),
            {"table": table, "needle": f"%{needle}%"},
        )
        .fetchall()
    )
    return [row[0] for row in rows]


def _replace_check(table: str, needle: str, name: str, sql: str) -> None:
    for existing in _checks(table, needle):
        op.drop_constraint(op.f(existing), table, type_="check")
    op.create_check_constraint(op.f(name), table, sql)


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_products_supplier_id_suppliers",
        "products",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_products_supplier_id", "products", ["supplier_id"])

    op.add_column(
        "product_variants",
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_product_variants_cost_price_non_negative",
        "product_variants",
        "cost_price IS NULL OR cost_price >= 0",
    )

    if op.get_bind().dialect.name == "postgresql":
        _replace_check(
            "order_activities",
            "'printed'",
            "ck_order_activities_action_known",
            _NEW_ACTION_SQL,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        payments = bind.scalar(
            sa.text("SELECT count(*) FROM order_activities WHERE action = 'payment_updated'")
        )
        if payments:
            raise RuntimeError(
                f"{payments} payment_updated activity row(s) exist; "
                "downgrade would break the activity check."
            )
        _replace_check(
            "order_activities",
            "'printed'",
            "ck_order_activities_action_known",
            _OLD_ACTION_SQL,
        )

    op.drop_constraint(
        "ck_product_variants_cost_price_non_negative",
        "product_variants",
        type_="check",
    )
    op.drop_column("product_variants", "cost_price")

    op.drop_index("ix_products_supplier_id", table_name="products")
    op.drop_constraint("fk_products_supplier_id_suppliers", "products", type_="foreignkey")
    op.drop_column("products", "supplier_id")
