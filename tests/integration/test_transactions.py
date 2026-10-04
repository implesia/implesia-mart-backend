"""Committed and rolled-back stock changes on PostgreSQL."""

import asyncio
import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.product import Product
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres


async def _stock(factory: async_sessionmaker[AsyncSession], product_id: uuid.UUID) -> int | None:
    async with factory() as db:
        return await db.scalar(select(Product.quantity).where(Product.id == product_id))


async def test_an_open_transaction_is_invisible_until_rollback(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        row = product(quantity=1)
        db.add(row)
        await db.commit()
        product_id = row.id

    release = asyncio.Event()
    started = asyncio.Event()

    async def writer() -> None:
        async with pg() as db:
            await db.execute(update(Product).where(Product.id == product_id).values(quantity=0))
            started.set()
            await release.wait()
            await db.rollback()

    task = asyncio.create_task(writer())
    await asyncio.wait_for(started.wait(), timeout=5)
    assert await _stock(pg, product_id) == 1
    release.set()
    await task
    assert await _stock(pg, product_id) == 1


async def test_a_commit_is_visible_to_another_session(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        row = product(quantity=2)
        db.add(row)
        await db.commit()
        product_id = row.id
        await db.execute(update(Product).where(Product.id == product_id).values(quantity=1))
        await db.commit()

    assert await _stock(pg, product_id) == 1
