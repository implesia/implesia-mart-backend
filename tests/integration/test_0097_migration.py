"""Migration 0097 adds order-desk columns and leaves existing totals alone."""

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

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0097_orders_management.py"
STAMP = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0097", MIGRATION)
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


async def _restore(db: AsyncSession) -> None:
    if "origin" not in await _columns(db):
        await _run(db, "upgrade")
    # 0097's upgrade recreates order_activities with the narrower action check.
    # Put the 0098 value back so later tests can store a customer message.
    present = await db.scalar(text("SELECT to_regclass('public.order_activities')"))
    if present is None:
        return
    path = (
        Path(__file__).parents[2] / "alembic" / "versions" / "0098_order_print_and_customer_sms.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0098_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def go(sync_conn) -> None:  # type: ignore[no-untyped-def]
        with Operations.context(MigrationContext.configure(sync_conn)):
            module.widen_activity_check()

    conn = await db.connection()
    await conn.run_sync(go)
    await db.commit()


async def test_0097_defaults_existing_rows_and_keeps_totals(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    order_id = uuid.uuid4()
    async with pg() as db:
        if "origin" not in await _columns(db):
            await _run(db, "upgrade")
        await _run(db, "downgrade")
    try:
        async with pg() as db:
            await db.execute(
                text(
                    "INSERT INTO orders ("
                    "id, number, source, status, payment_method, advance_amount, "
                    "payment_reference, customer_name, phone, email, district, area, address, "
                    "notes, delivery_zone, subtotal, shipping, total, courier_name, "
                    "tracking_number, inventory_held, created_at, updated_at"
                    ") VALUES ("
                    ":id, 'IM-KEEP0097', 'direct', 'confirmed', 'cod', 0, '', "
                    "'Rina Akter', '01700000000', '', 'Dhaka', 'Gulshan', 'House 1', '', "
                    "'inside', 1500, 70, 1570, '', '', true, :stamp, :stamp)"
                ),
                {"id": order_id, "stamp": STAMP},
            )
            await db.commit()
            await _run(db, "upgrade")
            row = (
                await db.execute(
                    text(
                        "SELECT subtotal, shipping, total, status, origin, call_status, "
                        "manual_discount, paid_amount, printed_at, ordered_at "
                        "FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            ).one()
            assert tuple(row) == (
                1500,
                70,
                1570,
                "confirmed",
                "online",
                "not_called",
                0,
                0,
                None,
                None,
            )
            await db.execute(
                text("UPDATE orders SET status = 'packed' WHERE id = :id"),
                {"id": order_id},
            )
            await db.commit()
            with pytest.raises(RuntimeError, match="packed"):
                await _run(db, "downgrade")
            await db.rollback()
            await db.execute(text("DELETE FROM orders WHERE id = :id"), {"id": order_id})
            await db.commit()
    finally:
        async with pg() as db:
            await _restore(db)
