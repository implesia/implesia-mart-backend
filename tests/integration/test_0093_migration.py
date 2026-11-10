"""Migration 0093 adds the ledger tables and leaves existing stock untouched."""

import importlib.util
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0093_inventory_ledger.py"
STAMP = datetime(2024, 1, 15, 8, 0, tzinfo=UTC)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0093", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(db: AsyncSession, direction: str) -> None:
    module = _migration()

    def go(sync_conn) -> None:  # type: ignore[no-untyped-def]
        with Operations.context(MigrationContext.configure(sync_conn)):
            getattr(module, direction)()

    conn = await db.connection()
    await conn.run_sync(go)
    await db.commit()


async def _tables(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN "
            "('suppliers', 'purchases', 'purchase_items', 'stock_movements', 'import_batches')"
        )
    )
    return {row[0] for row in rows}


async def _snapshot(db: AsyncSession, product_id: uuid.UUID, order_id: uuid.UUID) -> tuple:
    product = (
        await db.execute(
            text(
                "SELECT title, price, quantity, cost_price, status, updated_at "
                "FROM products WHERE id = :id"
            ),
            {"id": product_id},
        )
    ).one()
    order = (
        await db.execute(
            text(
                "SELECT number, status, total, customer_name, updated_at "
                "FROM orders WHERE id = :id"
            ),
            {"id": order_id},
        )
    ).one()
    return tuple(product), tuple(order)


async def test_0093_adds_tables_and_leaves_existing_rows(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    product_id = uuid.uuid4()
    order_id = uuid.uuid4()
    movement_id = uuid.uuid4()

    async with pg() as db:
        await _run(db, "downgrade")
        assert await _tables(db) == set()
        await db.execute(
            text(
                "INSERT INTO products ("
                "id, slug, title, price, status, quantity, cost_price, content, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :slug, 'Kept lamp', 1500, 'available', 7, 12.50, "
                "CAST('{}' AS jsonb), :stamp, :stamp)"
            ),
            {"id": product_id, "slug": f"kept-{product_id.hex[:8]}", "stamp": STAMP},
        )
        await db.execute(
            text(
                "INSERT INTO orders ("
                "id, number, source, status, payment_method, advance_amount, payment_reference, "
                "customer_name, phone, email, district, area, address, notes, delivery_zone, "
                "subtotal, shipping, total, courier_name, tracking_number, inventory_held, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, 'IM-KEEP0001', 'direct', 'confirmed', 'cod', 0, '', "
                "'Rina Akter', '01700000000', '', 'Dhaka', 'Gulshan', 'House 1', '', 'inside', "
                "1500, 70, 1570, '', '', true, :stamp, :stamp)"
            ),
            {"id": order_id, "stamp": STAMP},
        )
        await db.commit()
        before = await _snapshot(db, product_id, order_id)

    try:
        async with pg() as db:
            await _run(db, "upgrade")
            assert await _tables(db) == {
                "suppliers",
                "purchases",
                "purchase_items",
                "stock_movements",
                "import_batches",
            }
            trigger = (
                await db.execute(
                    text("SELECT tgname FROM pg_trigger WHERE tgname = 'stock_movements_no_change'")
                )
            ).scalar_one_or_none()
            assert trigger == "stock_movements_no_change"
            index = (
                await db.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE indexname = 'uq_stock_movements_opening_product'"
                    )
                )
            ).scalar_one_or_none()
            assert index == "uq_stock_movements_opening_product"
            assert await _snapshot(db, product_id, order_id) == before
            product = (
                await db.execute(
                    text("SELECT quantity, cost_price FROM products WHERE id = :id"),
                    {"id": product_id},
                )
            ).one()
            assert tuple(product) == (7, Decimal("12.50"))

            await db.execute(
                text(
                    "INSERT INTO stock_movements (id, product_id, quantity, movement_type) "
                    "VALUES (:id, :product_id, 7, 'opening')"
                ),
                {"id": movement_id, "product_id": product_id},
            )
            await db.commit()
            with pytest.raises(DBAPIError):
                await db.execute(
                    text("UPDATE stock_movements SET note = 'edited' WHERE id = :id"),
                    {"id": movement_id},
                )
                await db.commit()
            await db.rollback()
            with pytest.raises(DBAPIError):
                await db.execute(
                    text("UPDATE stock_movements SET quantity = 0 WHERE id = :id"),
                    {"id": movement_id},
                )
                await db.commit()
            await db.rollback()
            with pytest.raises(DBAPIError):
                await db.execute(
                    text("DELETE FROM stock_movements WHERE id = :id"),
                    {"id": movement_id},
                )
                await db.commit()
            await db.rollback()
            # Deleting a product nulls this reference. The movement row stays.
            await db.execute(
                text("UPDATE stock_movements SET product_id = NULL WHERE id = :id"),
                {"id": movement_id},
            )
            await db.commit()
            note = (
                await db.execute(
                    text(
                        "SELECT quantity, note, product_id FROM stock_movements WHERE id = :id"
                    ),
                    {"id": movement_id},
                )
            ).one()
            assert tuple(note) == (7, "", None)
            assert await _snapshot(db, product_id, order_id) == before

        async with pg() as db:
            await _run(db, "downgrade")
            assert await _tables(db) == set()
            gone = (
                await db.execute(
                    text(
                        "SELECT proname FROM pg_proc "
                        "WHERE proname = 'stock_movements_insert_only'"
                    )
                )
            ).scalar_one_or_none()
            assert gone is None
            assert await _snapshot(db, product_id, order_id) == before

        async with pg() as db:
            await _run(db, "upgrade")
            assert "stock_movements" in await _tables(db)
    finally:
        async with pg() as db:
            if "stock_movements" not in await _tables(db):
                await _run(db, "upgrade")
