"""Migration 0096 adds coupons and nullable order columns. Old totals stay put."""

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

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0096_coupons.py"
STAMP = datetime(2024, 6, 1, 9, 0, tzinfo=UTC)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0096", MIGRATION)
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
            "WHERE table_schema = 'public'"
        )
    )
    return {row[0] for row in rows}


async def _order_columns(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'orders'"
        )
    )
    return {row[0] for row in rows}


async def test_0096_adds_coupon_tables_and_leaves_old_order_totals(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    order_id = uuid.uuid4()
    async with pg() as db:
        tables = await _tables(db)
        assert {"coupons", "coupon_products", "coupon_categories", "coupon_redemptions"} <= tables
        assert {"coupon_code", "coupon_discount"} <= await _order_columns(db)
        module = _migration()
        assert module.revision == "0096"
        assert module.down_revision == "0095"

    try:
        async with pg() as db:
            await _run(db, "downgrade")
            tables = await _tables(db)
            assert "coupons" not in tables
            assert "coupon_redemptions" not in tables
            columns = await _order_columns(db)
            assert "coupon_code" not in columns
            assert "coupon_discount" not in columns
            await db.execute(
                text(
                    "INSERT INTO orders ("
                    "id, number, source, status, payment_method, advance_amount, "
                    "payment_reference, customer_name, phone, email, district, area, address, "
                    "notes, delivery_zone, subtotal, shipping, total, courier_name, "
                    "tracking_number, inventory_held, created_at, updated_at"
                    ") VALUES ("
                    ":id, 'IM-KEEP0096', 'direct', 'new', 'cod', 0, '', "
                    "'Rina Akter', '01700000000', '', 'Dhaka', 'Gulshan', 'House 1', '', "
                    "'inside', 1500, 70, 1570, '', '', true, :stamp, :stamp)"
                ),
                {"id": order_id, "stamp": STAMP},
            )
            await db.commit()
            await _run(db, "upgrade")
            code = (
                await db.execute(
                    text(
                        "SELECT data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'orders' "
                        "AND column_name = 'coupon_code'"
                    )
                )
            ).one()
            discount = (
                await db.execute(
                    text(
                        "SELECT data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'orders' "
                        "AND column_name = 'coupon_discount'"
                    )
                )
            ).one()
            assert code[1] == "YES"
            assert discount[0] == "integer"
            assert discount[1] == "YES"
            kept = (
                await db.execute(
                    text(
                        "SELECT number, total, coupon_code, coupon_discount "
                        "FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            ).one()
            assert kept[0] == "IM-KEEP0096"
            assert kept[1] == 1570
            assert kept[2] is None
            assert kept[3] is None
            assert "coupons" in await _tables(db)
    finally:
        async with pg() as db:
            if "coupon_code" not in await _order_columns(db):
                await _run(db, "upgrade")
