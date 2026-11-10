"""Migration 0094 adds channel and unit_cost and leaves existing rows alone."""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.postgres

MIGRATION = (
    Path(__file__).parents[2] / "alembic" / "versions" / "0094_order_channel_and_unit_cost.py"
)
STAMP = datetime(2024, 1, 15, 8, 0, tzinfo=UTC)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0094", MIGRATION)
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


# Indexes 0094 creates on columns that already exist. 0092's integration test
# drops delivered_at and returned_at and adds the columns back, and PostgreSQL
# drops these indexes with the columns. 0092 does not recreate them.
_TIMESTAMP_INDEXES = (
    ("ix_orders_delivered_at", "delivered_at"),
    ("ix_orders_returned_at", "returned_at"),
)


async def _columns(db: AsyncSession, table: str) -> set[str]:
    rows = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    return {row[0] for row in rows}


async def _order_index_names(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'orders'"
        )
    )
    return {row[0] for row in rows}


async def _restore_timestamp_indexes(db: AsyncSession) -> None:
    """Put back indexes 0092's column cycle removes from the shared database."""
    present = await _order_index_names(db)
    missing = [(name, column) for name, column in _TIMESTAMP_INDEXES if name not in present]
    if not missing:
        return
    for name, column in missing:
        await db.execute(text(f'CREATE INDEX "{name}" ON orders ("{column}")'))
    await db.commit()


async def _ensure_0094_applied(db: AsyncSession) -> None:
    """Start from the upgraded shape, including indexes create_all would have made.

    `channel` is not enough to mean 0094 was applied. create_all adds that
    column from the model, and the 0092 test can then remove the timestamp
    indexes without touching `channel`.
    """
    if "channel" not in await _columns(db, "orders"):
        await _run(db, "upgrade")
        return
    await _restore_timestamp_indexes(db)


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
                "SELECT number, source, status, subtotal, shipping, total, "
                "customer_name, phone, delivered_at, returned_at, created_at, updated_at "
                "FROM orders WHERE id = :id"
            ),
            {"id": order_id},
        )
    ).one()
    item = (
        await db.execute(
            text(
                "SELECT title, slug, unit_price, quantity, line_total, "
                "regular_price, created_at, updated_at "
                "FROM order_items WHERE order_id = :id"
            ),
            {"id": order_id},
        )
    ).one()
    return tuple(product), tuple(order), tuple(item)


async def _source_check(db: AsyncSession) -> str:
    definition = (
        await db.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'orders'::regclass AND conname = 'ck_orders_source_known'"
            )
        )
    ).scalar_one()
    return str(definition)


async def test_0094_adds_nullable_columns_and_leaves_existing_rows(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    product_id = uuid.uuid4()
    order_id = uuid.uuid4()
    item_id = uuid.uuid4()

    async with pg() as db:
        await _ensure_0094_applied(db)

    try:
        async with pg() as db:
            await _run(db, "downgrade")
            assert "channel" not in await _columns(db, "orders")
            assert "unit_cost" not in await _columns(db, "order_items")
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
                    "id, number, source, status, payment_method, advance_amount, "
                    "payment_reference, customer_name, phone, email, district, area, address, "
                    "notes, delivery_zone, subtotal, shipping, total, courier_name, "
                    "tracking_number, inventory_held, created_at, updated_at"
                    ") VALUES ("
                    ":id, 'IM-KEEP0094', 'direct', 'confirmed', 'cod', 0, '', "
                    "'Rina Akter', '01700000000', '', 'Dhaka', 'Gulshan', 'House 1', '', "
                    "'inside', 1500, 70, 1570, '', '', true, :stamp, :stamp)"
                ),
                {"id": order_id, "stamp": STAMP},
            )
            await db.execute(
                text(
                    "INSERT INTO order_items ("
                    "id, order_id, product_id, sku, title, slug, image_src, unit_price, "
                    "quantity, line_total, regular_price, selection, created_at, updated_at"
                    ") VALUES ("
                    ":id, :order_id, :product_id, '', 'Kept lamp', 'kept-lamp', '', 1500, 1, "
                    "1500, 1500, CAST('[]' AS jsonb), :stamp, :stamp)"
                ),
                {
                    "id": item_id,
                    "order_id": order_id,
                    "product_id": product_id,
                    "stamp": STAMP,
                },
            )
            await db.commit()
            before = await _snapshot(db, product_id, order_id)
            source_check = await _source_check(db)

        async with pg() as db:
            await _run(db, "upgrade")
            assert "channel" in await _columns(db, "orders")
            assert "unit_cost" in await _columns(db, "order_items")
            channel_meta = (
                await db.execute(
                    text(
                        "SELECT column_default, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'orders' "
                        "AND column_name = 'channel'"
                    )
                )
            ).one()
            cost_meta = (
                await db.execute(
                    text(
                        "SELECT column_default, is_nullable, numeric_precision, numeric_scale "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'order_items' "
                        "AND column_name = 'unit_cost'"
                    )
                )
            ).one()
            assert tuple(channel_meta) == (None, "YES")
            assert tuple(cost_meta) == (None, "YES", 12, 2)
            added = (
                await db.execute(
                    text("SELECT channel FROM orders WHERE id = :id"),
                    {"id": order_id},
                )
            ).scalar_one()
            assert added is None
            cost = (
                await db.execute(
                    text("SELECT unit_cost FROM order_items WHERE id = :id"),
                    {"id": item_id},
                )
            ).scalar_one()
            assert cost is None
            assert await _snapshot(db, product_id, order_id) == before
            assert await _source_check(db) == source_check
            with pytest.raises(DBAPIError):
                await db.execute(
                    text("UPDATE order_items SET unit_cost = -1 WHERE id = :id"),
                    {"id": item_id},
                )
                await db.commit()
            await db.rollback()
            cost_after = (
                await db.execute(
                    text("SELECT unit_cost FROM order_items WHERE id = :id"),
                    {"id": item_id},
                )
            ).scalar_one()
            assert cost_after is None
            assert await _snapshot(db, product_id, order_id) == before

        async with pg() as db:
            await _run(db, "downgrade")
            assert "channel" not in await _columns(db, "orders")
            assert "unit_cost" not in await _columns(db, "order_items")
            assert await _snapshot(db, product_id, order_id) == before

        async with pg() as db:
            await _run(db, "upgrade")
            assert "channel" in await _columns(db, "orders")
    finally:
        async with pg() as db:
            if "channel" not in await _columns(db, "orders"):
                await _run(db, "upgrade")
            else:
                await _restore_timestamp_indexes(db)
