"""A PostgreSQL row lock holds the next stock update until the lock is released."""

import asyncio

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.product import Product
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres


async def test_a_row_lock_blocks_the_second_stock_update(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        row = product(quantity=1)
        db.add(row)
        await db.commit()
        product_id = row.id

    locked = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def hold() -> None:
        async with pg() as db:
            await db.scalar(select(Product.id).where(Product.id == product_id).with_for_update())
            locked.set()
            await release.wait()
            await db.commit()

    async def change() -> None:
        await locked.wait()
        async with pg() as db:
            await db.execute(
                update(Product)
                .where(Product.id == product_id, Product.quantity == 1)
                .values(quantity=0)
            )
            finished.set()
            await db.commit()

    holder = asyncio.create_task(hold())
    changer: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)
        changer = asyncio.create_task(change())
        blocked = False
        try:
            await asyncio.wait_for(finished.wait(), timeout=0.4)
        except TimeoutError:
            blocked = True
        assert blocked
    finally:
        release.set()
        await holder
        if changer is not None:
            await changer

    async with pg() as db:
        left = await db.scalar(select(Product.quantity).where(Product.id == product_id))
    assert left == 0
    assert finished.is_set()
