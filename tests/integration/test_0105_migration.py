"""Migration 0105 adds products.supplier_id, product_variants.cost_price, and widens actions."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.postgres

MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "0105_product_supplier_and_variant_cost.py"
)


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0105", MIGRATION)
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


async def _columns(db: AsyncSession, table: str) -> dict[str, str]:
    rows = await db.execute(
        text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    return {row[0]: row[1] for row in rows}


async def test_0105_adds_supplier_id_and_variant_cost_and_rolls_back(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    module = _migration()
    assert module.revision == "0105"
    assert module.down_revision == "0104"

    async with pg() as db:
        assert (await _columns(db, "products"))["supplier_id"] == "YES"
        assert (await _columns(db, "product_variants"))["cost_price"] == "YES"

    try:
        async with pg() as db:
            await _run(db, "downgrade")
            assert "supplier_id" not in await _columns(db, "products")
            assert "cost_price" not in await _columns(db, "product_variants")

            await _run(db, "upgrade")
            assert (await _columns(db, "products"))["supplier_id"] == "YES"
            assert (await _columns(db, "product_variants"))["cost_price"] == "YES"
    finally:
        async with pg() as db:
            if "supplier_id" not in await _columns(db, "products"):
                await _run(db, "upgrade")
