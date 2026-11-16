"""Migration 0098 adds nullable SMS claims and leaves existing totals alone."""

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
    Path(__file__).parents[2] / "alembic" / "versions" / "0098_order_print_and_customer_sms.py"
)
STAMP = datetime(2024, 6, 1, 8, 0, tzinfo=UTC)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0098", MIGRATION)
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


async def _index(db: AsyncSession) -> bool:
    found = await db.scalar(
        text(
            "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname = 'ix_orders_tracking_number_lower'"
        )
    )
    return found is not None


async def test_0098_adds_nullable_claims_and_keeps_totals(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    order_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    module = _migration()
    assert module.down_revision == "0097"
    async with pg() as db:
        assert "customer_sms_confirmed_at" in await _columns(db)
        assert await _index(db)
    try:
        async with pg() as db:
            await _run(db, "downgrade")
            assert "customer_sms_confirmed_at" not in await _columns(db)
            assert "customer_sms_shipped_at" not in await _columns(db)
            assert not await _index(db)
            await db.execute(
                text(
                    "INSERT INTO orders ("
                    "id, number, source, status, payment_method, advance_amount, "
                    "payment_reference, customer_name, phone, email, district, area, address, "
                    "notes, delivery_zone, subtotal, shipping, total, courier_name, "
                    "tracking_number, inventory_held, created_at, updated_at"
                    ") VALUES ("
                    ":id, 'IM-KEEP0098', 'direct', 'confirmed', 'cod', 0, '', "
                    "'Rina Akter', '01700000000', '', 'Dhaka', 'Gulshan', 'House 1', '', "
                    "'inside', 1500, 70, 1570, '', '', true, :stamp, :stamp)"
                ),
                {"id": order_id, "stamp": STAMP},
            )
            await db.commit()
            await _run(db, "upgrade")
            kept = (
                await db.execute(
                    text(
                        "SELECT subtotal, shipping, total, status, "
                        "customer_sms_confirmed_at, customer_sms_shipped_at "
                        "FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            ).one()
            assert tuple(kept) == (1500, 70, 1570, "confirmed", None, None)
            assert await _index(db)
            definition = await db.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_order_activities_action_known'"
                )
            )
            assert definition is not None
            assert "customer_message" in definition
            await db.execute(
                text(
                    "INSERT INTO order_activities "
                    "(id, order_id, action, summary, detail) VALUES "
                    "(:id, :order_id, 'customer_message', "
                    "'Customer message logged for confirmed', '{}'::jsonb)"
                ),
                {"id": activity_id, "order_id": order_id},
            )
            await db.commit()
            with pytest.raises(RuntimeError, match="customer message"):
                await _run(db, "downgrade")
            await db.rollback()
            await db.execute(
                text("DELETE FROM order_activities WHERE id = :id"),
                {"id": activity_id},
            )
            await db.commit()
    finally:
        async with pg() as db:
            if "customer_sms_confirmed_at" not in await _columns(db):
                await _run(db, "upgrade")
