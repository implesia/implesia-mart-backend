"""PostgreSQL check constraints, foreign keys, and unique indexes."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit_event import AuditEvent
from app.models.order import OrderIdempotency
from app.models.refresh_token import RefreshToken
from app.models.user import User
from tests.integration.helpers import audit_event, order, product, refresh_token, user

pytestmark = pytest.mark.postgres


async def _rejects(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_negative_price_and_quantity_are_rejected(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        db.add(product(price=-1))
        await _rejects(db)
    async with pg() as db:
        db.add(product(quantity=-1))
        await _rejects(db)


async def test_an_unknown_order_status_is_rejected(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        row = order()
        row.status = "nope"
        db.add(row)
        await _rejects(db)


async def test_two_inserts_of_the_same_email_keep_one_user(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    email = f"race-{uuid.uuid4().hex[:12]}@implesia.test"
    gate = asyncio.Barrier(2)

    async def insert() -> str:
        async with pg() as db:
            db.add(user(email))
            await gate.wait()
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return "conflict"
        return "ok"

    results = await asyncio.wait_for(asyncio.gather(insert(), insert()), timeout=15)
    assert sorted(results) == ["conflict", "ok"]
    async with pg() as db:
        count = await db.scalar(select(func.count()).select_from(User).where(User.email == email))
    assert count == 1


async def test_two_inserts_of_the_same_idempotency_key_keep_one_row(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        placed = order()
        db.add(placed)
        await db.commit()
        order_id = placed.id

    key = uuid.uuid4().hex
    gate = asyncio.Barrier(2)

    async def insert() -> str:
        async with pg() as db:
            db.add(OrderIdempotency(actor="anonymous", idempotency_key=key, order_id=order_id))
            await gate.wait()
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return "conflict"
        return "ok"

    results = await asyncio.wait_for(asyncio.gather(insert(), insert()), timeout=15)
    assert sorted(results) == ["conflict", "ok"]
    async with pg() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(OrderIdempotency)
            .where(OrderIdempotency.idempotency_key == key)
        )
    assert count == 1


async def test_deleting_a_user_cascades_refresh_tokens_and_keeps_audit_history(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        account = user()
        db.add(account)
        await db.commit()
        account_id = account.id
        db.add(refresh_token(account_id))
        event = audit_event(account_id)
        db.add(event)
        await db.commit()
        event_id = event.id
        await db.execute(delete(User).where(User.id == account_id))
        await db.commit()

    async with pg() as db:
        tokens = await db.scalar(select(func.count()).select_from(RefreshToken))
        saved = await db.get(AuditEvent, event_id)
    assert tokens == 0
    assert saved is not None
    assert saved.actor_user_id is None
