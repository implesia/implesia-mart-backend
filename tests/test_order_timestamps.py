"""First delivery and return times are stored once and shown on the admin order.

SQLite drops the timezone label on read, so this file checks the value and that a second
transition does not replace it. PostgreSQL checks the timestamptz offset in
tests/integration/test_order_timestamps.py.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from tests.test_orders import SHIPPING, _key, _move, _place
from tests.test_products import _create


async def test_status_change_stamps_once_and_admin_reads_it(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    product = await _create(client, auth_headers, title="Stamp lamp", price=500, quantity=3)
    order_id = await _place(client, auth_headers, product["id"])

    confirmed = await _move(client, auth_headers, order_id, "confirmed")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["delivered_at"] is None
    assert confirmed.json()["returned_at"] is None
    shipped = await _move(client, auth_headers, order_id, "shipped")
    assert shipped.json()["delivered_at"] is None

    delivered = await _move(client, auth_headers, order_id, "delivered")
    assert delivered.status_code == 200, delivered.text
    body = delivered.json()
    first = body["delivered_at"]
    assert first is not None and body["returned_at"] is None

    # The state machine does not re-enter delivered. Put the row back to shipped without
    # clearing the stamp, then deliver again: the first time must stay.
    await db_session.execute(
        update(Order).where(Order.id == uuid.UUID(order_id)).values(status="shipped")
    )
    await db_session.commit()
    again = await _move(client, auth_headers, order_id, "delivered")
    assert again.status_code == 200, again.text
    assert again.json()["delivered_at"] == first
    assert again.json()["returned_at"] is None

    returned = await _move(client, auth_headers, order_id, "returned")
    assert returned.status_code == 200, returned.text
    assert returned.json()["delivered_at"] == first
    assert returned.json()["returned_at"] is not None

    admin = await client.get(f"/api/v1/admin/orders/{order_id}", headers=auth_headers)
    assert admin.status_code == 200, admin.text
    assert admin.json()["delivered_at"] == first
    listed = await client.get("/api/v1/admin/orders", headers=auth_headers)
    match = next(item for item in listed.json()["items"] if item["id"] == order_id)
    assert match["delivered_at"] == first
    assert match["returned_at"] == returned.json()["returned_at"]

    found = await client.post(
        "/api/v1/orders/lookup",
        json={"number": admin.json()["number"], "phone": SHIPPING["phone"]},
    )
    assert found.status_code == 200, found.text
    assert "delivered_at" not in found.json()
    assert "returned_at" not in found.json()


async def test_public_place_order_has_null_timestamps(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Fresh lamp", price=500, quantity=2)
    placed = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
        },
    )
    assert placed.status_code == 201, placed.text
    assert placed.json()["delivered_at"] is None
    assert placed.json()["returned_at"] is None
