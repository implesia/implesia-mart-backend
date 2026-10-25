"""Category tree guarantees that only PostgreSQL can give: trigger, FKs, concurrency."""

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import ConflictError
from app.models.category import Category
from app.models.product import Product
from app.services import category_service
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres


def _cat(slug: str, parent: Category | None = None) -> Category:
    return Category(id=uuid.uuid4(), slug=slug, name=slug, parent_id=parent.id if parent else None)


async def test_the_trigger_rejects_a_cycle_written_around_the_api(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    a = _cat("a")
    b = _cat("b", a)
    c = _cat("c", b)
    async with pg() as db:
        db.add(a)
        await db.flush()
        db.add(b)
        await db.flush()
        db.add(c)
        await db.commit()
    async with pg() as db:
        with pytest.raises((IntegrityError, DBAPIError)) as caught:
            await db.execute(
                text("UPDATE categories SET parent_id = :c WHERE id = :a"), {"c": c.id, "a": a.id}
            )
        assert "cycle" in str(caught.value)
        await db.rollback()
    async with pg() as db:
        with pytest.raises((IntegrityError, DBAPIError)):
            await db.execute(
                text("UPDATE categories SET parent_id = id WHERE id = :a"), {"a": a.id}
            )
        await db.rollback()


async def test_deleting_a_category_with_children_or_products_is_blocked_by_the_database(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    parent = _cat("parent")
    child = _cat("child", parent)
    async with pg() as db:
        db.add(parent)
        await db.flush()
        db.add(child)
        item = product()
        item.category_id = child.id
        await db.flush()
        db.add(item)
        await db.commit()
    for victim in (parent, child):
        async with pg() as db:
            with pytest.raises(IntegrityError):
                await db.execute(text("DELETE FROM categories WHERE id = :i"), {"i": victim.id})
            await db.rollback()


async def test_service_delete_reassigns_atomically(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    source = _cat("source")
    target = _cat("target")
    async with pg() as db:
        db.add_all([source, target])
        await db.flush()
        item = product()
        item.category_id = source.id
        db.add(item)
        await db.commit()
        item_id = item.id
    async with pg() as db:
        row = await category_service.get(db, source.id)
        with pytest.raises(ConflictError):
            await category_service.delete_category(db, row)
        await db.rollback()
    async with pg() as db:
        row = await category_service.get(db, source.id)
        await category_service.delete_category(db, row, reassign_to=target.id)
    async with pg() as db:
        moved = await db.get(Product, item_id)
        assert moved is not None and moved.category_id == target.id
        assert await db.scalar(select(Category.id).where(Category.id == source.id)) is None


async def test_two_opposite_moves_cannot_close_a_loop(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    """A under B and B under A, requested together: the advisory lock lets only one win."""
    a = _cat("left")
    b = _cat("right")
    async with pg() as db:
        db.add_all([a, b])
        await db.commit()

    async def move(child: uuid.UUID, parent: uuid.UUID) -> bool:
        async with pg() as db:
            try:
                await db.execute(
                    text("UPDATE categories SET parent_id = :p WHERE id = :c"),
                    {"p": parent, "c": child},
                )
                await db.commit()
            except (IntegrityError, DBAPIError):
                await db.rollback()
                return False
            return True

    results = await asyncio.wait_for(asyncio.gather(move(a.id, b.id), move(b.id, a.id)), 15)
    assert sorted(results) == [False, True]
    async with pg() as db:
        rows = (await db.execute(select(Category.slug, Category.parent_id))).all()
        assert sum(parent is not None for _slug, parent in rows) == 1


async def test_slug_is_unique_in_the_database(pg: async_sessionmaker[AsyncSession]) -> None:
    async with pg() as db:
        db.add_all([_cat("same"), _cat("same")])
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
