"""Inventory ledger: suppliers, purchases, stock movements, import batches

Revision ID: 0093
Revises: 0092
Create Date: 2026-11-09

Adds five tables and their indexes, checks, and foreign keys. On PostgreSQL it
also adds a trigger that rejects UPDATE and DELETE on stock_movements.

No existing table, column, or row is changed. Product and variant quantities
stay as they are. Downgrade drops only these tables (and the trigger).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0093"
down_revision: str | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INSERT_ONLY = sa.text(
    """
    CREATE FUNCTION stock_movements_insert_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        -- A parent delete may null a foreign key. The row itself stays, and
        -- every other column is frozen.
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'stock_movements is insert-only';
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.quantity IS DISTINCT FROM OLD.quantity
           OR NEW.movement_type IS DISTINCT FROM OLD.movement_type
           OR NEW.unit_cost IS DISTINCT FROM OLD.unit_cost
           OR NEW.note IS DISTINCT FROM OLD.note
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NOT (NEW.product_id IS NOT DISTINCT FROM OLD.product_id OR NEW.product_id IS NULL)
           OR NOT (NEW.variant_id IS NOT DISTINCT FROM OLD.variant_id OR NEW.variant_id IS NULL)
           OR NOT (NEW.order_id IS NOT DISTINCT FROM OLD.order_id OR NEW.order_id IS NULL)
           OR NOT (NEW.purchase_id IS NOT DISTINCT FROM OLD.purchase_id OR NEW.purchase_id IS NULL)
           OR NOT (
                NEW.import_batch_id IS NOT DISTINCT FROM OLD.import_batch_id
                OR NEW.import_batch_id IS NULL
           )
           OR NOT (NEW.actor_id IS NOT DISTINCT FROM OLD.actor_id OR NEW.actor_id IS NULL)
        THEN
            RAISE EXCEPTION 'stock_movements is insert-only';
        END IF;
        RETURN NEW;
    END;
    $$
    """
)
_INSERT_ONLY_TRIGGER = sa.text(
    """
    CREATE TRIGGER stock_movements_no_change
    BEFORE UPDATE OR DELETE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION stock_movements_insert_only()
    """
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _text(name: str, length: int) -> sa.Column:
    return sa.Column(name, sa.String(length=length), nullable=False, server_default="")


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        _text("phone", 40),
        _text("address", 500),
        _text("note", 500),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
    )
    op.create_index(op.f("ix_suppliers_name"), "suppliers", ["name"], unique=False)

    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("import_type", sa.String(length=32), nullable=False),
        _text("file_name", 255),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        _created(),
        sa.CheckConstraint(
            "import_type IN ('purchases', 'opening', 'stock_count', 'cost_price')",
            name=op.f("ck_import_batches_type_known"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_import_batches_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batches")),
    )
    op.create_index(
        op.f("ix_import_batches_actor_id"), "import_batches", ["actor_id"], unique=False
    )
    op.create_index(
        "ix_import_batches_file_hash", "import_batches", ["file_hash"], unique=False
    )

    op.create_table(
        "purchases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("purchased_on", sa.Date(), nullable=False),
        _text("invoice_no", 64),
        _text("note", 500),
        sa.Column("import_batch_id", sa.Uuid(), nullable=True),
        _created(),
        _updated(),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_purchases_supplier_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name=op.f("fk_purchases_import_batch_id_import_batches"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchases")),
    )
    op.create_index(op.f("ix_purchases_supplier_id"), "purchases", ["supplier_id"], unique=False)
    op.create_index(op.f("ix_purchases_purchased_on"), "purchases", ["purchased_on"], unique=False)
    op.create_index(
        op.f("ix_purchases_import_batch_id"), "purchases", ["import_batch_id"], unique=False
    )
    op.create_index(
        "ix_purchases_supplier_date", "purchases", ["supplier_id", "purchased_on"], unique=False
    )

    op.create_table(
        "purchase_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "quantity >= 1 AND quantity <= 1000000",
            name=op.f("ck_purchase_items_quantity_in_range"),
        ),
        sa.CheckConstraint(
            "unit_cost >= 0",
            name=op.f("ck_purchase_items_unit_cost_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
            name=op.f("fk_purchase_items_purchase_id_purchases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_purchase_items_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_purchase_items_variant_id_product_variants"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_items")),
    )
    op.create_index(
        op.f("ix_purchase_items_purchase_id"), "purchase_items", ["purchase_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_items_product_id"), "purchase_items", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_items_variant_id"), "purchase_items", ["variant_id"], unique=False
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(length=16), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("purchase_id", sa.Uuid(), nullable=True),
        sa.Column("import_batch_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        _text("note", 500),
        _created(),
        sa.CheckConstraint(
            "movement_type IN ('opening', 'purchase', 'sale', 'return', 'cancel', 'adjustment')",
            name=op.f("ck_stock_movements_type_known"),
        ),
        sa.CheckConstraint(
            "quantity >= -1000000 AND quantity <= 1000000",
            name=op.f("ck_stock_movements_quantity_bounds"),
        ),
        sa.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0",
            name=op.f("ck_stock_movements_unit_cost_non_negative"),
        ),
        sa.CheckConstraint(
            "(CASE WHEN order_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN purchase_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN import_batch_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name=op.f("ck_stock_movements_one_source"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_stock_movements_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_stock_movements_variant_id_product_variants"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_stock_movements_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
            name=op.f("fk_stock_movements_purchase_id_purchases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name=op.f("fk_stock_movements_import_batch_id_import_batches"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_stock_movements_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_movements")),
    )
    op.create_index(
        op.f("ix_stock_movements_product_id"), "stock_movements", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_variant_id"), "stock_movements", ["variant_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_movement_type"), "stock_movements", ["movement_type"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_order_id"), "stock_movements", ["order_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_purchase_id"), "stock_movements", ["purchase_id"], unique=False
    )
    op.create_index(
        op.f("ix_stock_movements_import_batch_id"),
        "stock_movements",
        ["import_batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_stock_movements_actor_id"), "stock_movements", ["actor_id"], unique=False
    )
    op.create_index(
        "ix_stock_movements_created_at", "stock_movements", ["created_at"], unique=False
    )
    op.create_index(
        "uq_stock_movements_opening_product",
        "stock_movements",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("movement_type = 'opening' AND variant_id IS NULL"),
        sqlite_where=sa.text("movement_type = 'opening' AND variant_id IS NULL"),
    )
    op.create_index(
        "uq_stock_movements_opening_variant",
        "stock_movements",
        ["variant_id"],
        unique=True,
        postgresql_where=sa.text("movement_type = 'opening' AND variant_id IS NOT NULL"),
        sqlite_where=sa.text("movement_type = 'opening' AND variant_id IS NOT NULL"),
    )
    if _is_postgres():
        op.execute(_INSERT_ONLY)
        op.execute(_INSERT_ONLY_TRIGGER)


def downgrade() -> None:
    if _is_postgres():
        op.execute(sa.text("DROP TRIGGER IF EXISTS stock_movements_no_change ON stock_movements"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS stock_movements_insert_only()"))
    op.drop_table("stock_movements")
    op.drop_table("purchase_items")
    op.drop_table("purchases")
    op.drop_table("import_batches")
    op.drop_table("suppliers")
