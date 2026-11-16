"""Migration 0095 adds a nullable claim timestamp and leaves existing rows alone."""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.postgres

MIGRATION = (
    Path(__file__).parents[2] / "alembic" / "versions" / "0095_order_telegram_notified_at.py"
)
STAMP = datetime(2024, 6, 1, 9, 0, tzinfo=UTC)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0095", MIGRATION)
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


async def _columns(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'orders'"
        )
    )
    return {row[0] for row in rows}


async def _created_at_indexes(db: AsyncSession) -> list[str]:
    rows = await db.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'orders' "
            "AND indexdef ILIKE '%created_at%'"
        )
    )
    return sorted(row[0] for row in rows)


async def test_0095_adds_a_nullable_column_and_keeps_the_created_at_index(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    order_id = uuid.uuid4()
    async with pg() as db:
        assert "telegram_notified_at" in await _columns(db)
        assert await _created_at_indexes(db) == ["ix_orders_created_at"]
        module = _migration()
        assert module.down_revision == "0094"

    try:
        async with pg() as db:
            await _run(db, "downgrade")
            assert "telegram_notified_at" not in await _columns(db)
            assert await _created_at_indexes(db) == ["ix_orders_created_at"]
            await db.execute(
                text(
                    "INSERT INTO orders ("
                    "id, number, source, status, payment_method, advance_amount, "
                    "payment_reference, customer_name, phone, email, district, area, address, "
                    "notes, delivery_zone, subtotal, shipping, total, courier_name, "
                    "tracking_number, inventory_held, created_at, updated_at"
                    ") VALUES ("
                    ":id, 'IM-KEEP0095', 'direct', 'new', 'cod', 0, '', "
                    "'Rina Akter', '01700000000', '', 'Dhaka', 'Gulshan', 'House 1', '', "
                    "'inside', 1500, 70, 1570, '', '', true, :stamp, :stamp)"
                ),
                {"id": order_id, "stamp": STAMP},
            )
            await db.commit()
            await _run(db, "upgrade")
            column = (
                await db.execute(
                    text(
                        "SELECT data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'orders' "
                        "AND column_name = 'telegram_notified_at'"
                    )
                )
            ).one()
            assert column[0] == "timestamp with time zone"
            assert column[1] == "YES"
            kept = (
                await db.execute(
                    text("SELECT number, total, telegram_notified_at FROM orders WHERE id = :id"),
                    {"id": order_id},
                )
            ).one()
            assert kept[0] == "IM-KEEP0095"
            assert kept[1] == 1570
            assert kept[2] is None
            assert await _created_at_indexes(db) == ["ix_orders_created_at"]
    finally:
        async with pg() as db:
            if "telegram_notified_at" not in await _columns(db):
                await _run(db, "upgrade")
