"""Migration 0092 on PostgreSQL: columns, index, check, backfill, and rollback."""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit_event import AuditEvent

pytestmark = pytest.mark.postgres

MIGRATION = (
    Path(__file__).parents[2] / "alembic" / "versions" / "0092_order_timestamps_and_cost_price.py"
)

DELIVERED_FIRST = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)
DELIVERED_LATER = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
RETURNED_AT = datetime(2024, 7, 2, 9, 30, tzinfo=UTC)
# Distinct from any status-change time, so a backfill that copied these would fail the test.
ORDER_CREATED = datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
ORDER_UPDATED = datetime(2023, 8, 8, 0, 0, tzinfo=UTC)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0092", MIGRATION)
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


async def _columns(db: AsyncSession, table: str, names: tuple[str, ...]) -> set[str]:
    rows = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    wanted = set(names)
    return {row[0] for row in rows if row[0] in wanted}


async def _insert_order(db: AsyncSession, order_id: uuid.UUID, number: str, status: str) -> None:
    await db.execute(
        text(
            "INSERT INTO orders ("
            "id, number, source, status, payment_method, advance_amount, payment_reference, "
            "customer_name, phone, email, district, area, address, notes, delivery_zone, "
            "subtotal, shipping, total, courier_name, tracking_number, inventory_held, "
            "created_at, updated_at"
            ") VALUES ("
            ":id, :number, 'direct', :status, 'cod', 0, '', "
            "'Rina Akter', '01700000000', '', 'Dhaka', 'Gulshan', 'House 1', '', 'inside', "
            "1000, 70, 1070, '', '', true, :created_at, :updated_at"
            ")"
        ),
        {
            "id": order_id,
            "number": number,
            "status": status,
            "created_at": ORDER_CREATED,
            "updated_at": ORDER_UPDATED,
        },
    )


def _audit(order_id: uuid.UUID, to_status: str, when: datetime) -> AuditEvent:
    return AuditEvent(
        action="ORDER_STATUS_CHANGED",
        target_type="order",
        target_id=str(order_id),
        event_metadata={"from": "shipped", "to": to_status, "number": "IM-TEST"},
        created_at=when,
    )


async def _snapshot(db: AsyncSession) -> list[tuple]:
    rows = await db.execute(
        text(
            "SELECT number, status, total, customer_name, created_at, updated_at "
            "FROM orders ORDER BY number"
        )
    )
    return [tuple(row) for row in rows]


async def test_0092_adds_columns_backfills_history_and_rolls_back(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    delivered_id = uuid.uuid4()
    returned_id = uuid.uuid4()
    silent_id = uuid.uuid4()
    shipped_id = uuid.uuid4()
    product_id = uuid.uuid4()

    async with pg() as db:
        await _run(db, "downgrade")
        assert await _columns(db, "orders", ("delivered_at", "returned_at")) == set()
        assert await _columns(db, "products", ("cost_price",)) == set()
        await _insert_order(db, delivered_id, "IM-AAA00001", "delivered")
        await _insert_order(db, returned_id, "IM-AAA00002", "returned")
        await _insert_order(db, silent_id, "IM-AAA00003", "delivered")
        await _insert_order(db, shipped_id, "IM-AAA00004", "shipped")
        await db.execute(
            text(
                "INSERT INTO products (id, slug, title, price, status, content) "
                "VALUES (:id, :slug, 'Kept lamp', 1500, 'available', CAST('{}' AS jsonb))"
            ),
            {"id": product_id, "slug": f"kept-{product_id.hex[:8]}"},
        )
        # Two delivered events: the earlier one is the first delivery. The shipped order also
        # has a delivered event, but its current status is not delivered or returned.
        db.add(_audit(delivered_id, "delivered", DELIVERED_LATER))
        db.add(_audit(delivered_id, "delivered", DELIVERED_FIRST))
        db.add(_audit(returned_id, "delivered", DELIVERED_FIRST))
        db.add(_audit(returned_id, "returned", RETURNED_AT))
        db.add(_audit(shipped_id, "delivered", DELIVERED_LATER))
        await db.commit()
        before = await _snapshot(db)

    try:
        async with pg() as db:
            await _run(db, "upgrade")
            assert await _columns(db, "orders", ("delivered_at", "returned_at")) == {
                "delivered_at",
                "returned_at",
            }
            assert await _columns(db, "products", ("cost_price",)) == {"cost_price"}
            kinds = (
                await db.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND ("
                        " (table_name = 'orders' AND column_name IN "
                        "('delivered_at', 'returned_at')) "
                        " OR (table_name = 'products' AND column_name = 'cost_price')) "
                        "ORDER BY column_name"
                    )
                )
            ).all()
            by_name = {row[0]: row for row in kinds}
            assert by_name["delivered_at"][1] == "timestamp with time zone"
            assert by_name["returned_at"][1] == "timestamp with time zone"
            assert by_name["cost_price"][1] == "numeric"
            assert all(row[2] == "YES" for row in kinds)

            index = (
                await db.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = 'orders' "
                        "AND indexname = 'ix_orders_status'"
                    )
                )
            ).scalar_one_or_none()
            assert index == "ix_orders_status"
            check = (
                await db.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'ck_products_cost_price_non_negative'"
                    )
                )
            ).scalar_one()
            assert "cost_price" in check and ">=" in check

            times = {
                row[0]: (row[1], row[2], row[3], row[4])
                for row in (
                    await db.execute(
                        text(
                            "SELECT number, status, delivered_at, returned_at, updated_at "
                            "FROM orders ORDER BY number"
                        )
                    )
                ).all()
            }
            assert times["IM-AAA00001"] == ("delivered", DELIVERED_FIRST, None, ORDER_UPDATED)
            assert times["IM-AAA00002"] == ("returned", DELIVERED_FIRST, RETURNED_AT, ORDER_UPDATED)
            # No recorded status change: stay NULL. Do not copy created_at or updated_at.
            assert times["IM-AAA00003"] == ("delivered", None, None, ORDER_UPDATED)
            # History exists, but the order is not currently delivered or returned.
            assert times["IM-AAA00004"] == ("shipped", None, None, ORDER_UPDATED)
            assert await _snapshot(db) == before

            product = (
                await db.execute(
                    text("SELECT title, price, cost_price FROM products WHERE id = :id"),
                    {"id": product_id},
                )
            ).one()
            assert tuple(product) == ("Kept lamp", 1500, None)

            with pytest.raises(IntegrityError):
                await db.execute(
                    text("UPDATE products SET cost_price = -1 WHERE id = :id"),
                    {"id": product_id},
                )
                await db.commit()
            await db.rollback()
            price = (
                await db.execute(
                    text("SELECT price, cost_price FROM products WHERE id = :id"),
                    {"id": product_id},
                )
            ).one()
            assert tuple(price) == (1500, None)

        async with pg() as db:
            await _run(db, "downgrade")
            assert await _columns(db, "orders", ("delivered_at", "returned_at")) == set()
            assert await _columns(db, "products", ("cost_price",)) == set()
            gone = (
                await db.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = 'orders' "
                        "AND indexname = 'ix_orders_status'"
                    )
                )
            ).scalar_one_or_none()
            assert gone is None
            check_gone = (
                await db.execute(
                    text(
                        "SELECT 1 FROM pg_constraint "
                        "WHERE conname = 'ck_products_cost_price_non_negative'"
                    )
                )
            ).scalar_one_or_none()
            assert check_gone is None
            assert await _snapshot(db) == before
            kept = (
                await db.execute(
                    text("SELECT title, price FROM products WHERE id = :id"),
                    {"id": product_id},
                )
            ).one()
            assert tuple(kept) == ("Kept lamp", 1500)

        async with pg() as db:
            await _run(db, "upgrade")
            again = (
                await db.execute(
                    text("SELECT delivered_at FROM orders WHERE number = 'IM-AAA00001'")
                )
            ).scalar_one()
            assert again == DELIVERED_FIRST
    finally:
        async with pg() as db:
            present = await _columns(db, "orders", ("delivered_at", "returned_at"))
            if present != {"delivered_at", "returned_at"}:
                await _run(db, "upgrade")
