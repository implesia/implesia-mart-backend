import re
import uuid

from httpx import AsyncClient

from tests.test_products import _create

SHIPPING = {
    "customer_name": "Rina Akter",
    "phone": "01700000000",
    "email": "",
    "district": "চট্টগ্রাম",
    "area": "আগ্রাবাদ",
    "address": "House 12, Road 4, Agrabad",
    "notes": "",
}


def _key() -> str:
    return uuid.uuid4().hex


async def _stock(client: AsyncClient, headers: dict[str, str], product_id: str) -> dict:
    response = await client.get(f"/api/v1/admin/products/{product_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_direct_order_ignores_client_prices_and_replays(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=15000, quantity=4)
    rejected = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 1}],
            **SHIPPING,
            "shipping": 0,
            "total": 1,
        },
    )
    assert rejected.status_code == 422

    key = _key()
    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": key},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 2}],
            **SHIPPING,
            "district": "ঢাকা",
        },
    )
    assert placed.status_code == 201, placed.text
    body = placed.json()
    assert body["anonymous"] is True
    assert body["payment_method"] == "cod"
    assert body["items"][0]["unit_price"] == 15000
    assert body["items"][0]["line_total"] == 30000
    assert body["subtotal"] == 30000
    assert body["shipping"] == 70
    assert body["total"] == 30070
    assert body["delivery_zone"] == "inside"
    assert body["number"].startswith("IM-")

    left = await _stock(client, auth_headers, product["id"])
    assert left["quantity"] == 2

    replay = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": key},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 2}],
            **SHIPPING,
            "district": "ঢাকা",
        },
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == body["id"]
    again = await _stock(client, auth_headers, product["id"])
    assert again["quantity"] == 2

    stolen = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": key, "X-Cart-Token": "d" * 32},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
        },
    )
    assert stolen.status_code == 409


async def test_quote_does_not_take_stock_and_cart_order_clears_the_cart(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Cart gown", price=500, quantity=3)
    added = await client.post(
        "/api/v1/cart/items",
        json={"product_id": product["id"], "quantity": 2},
    )
    assert added.status_code == 200, added.text
    token = added.json()["cart_token"]
    guest = {"X-Cart-Token": token}

    quoted = await client.post(
        "/api/v1/orders/quote",
        headers=guest,
        json={"source": "cart", "district": "চট্টগ্রাম"},
    )
    assert quoted.status_code == 200, quoted.text
    quote = quoted.json()
    assert quote["items"][0]["unit_price"] == 500
    assert quote["items"][0]["line_total"] == 1000
    assert quote["shipping"] == 130
    assert quote["total"] == 1130
    assert quote["delivery_zone"] == "outside"
    assert quote["items"][0]["max_quantity"] == 3
    untouched = await _stock(client, auth_headers, product["id"])
    assert untouched["quantity"] == 3

    placed = await client.post(
        "/api/v1/orders",
        headers={**guest, "Idempotency-Key": _key()},
        json={"source": "cart", **SHIPPING},
    )
    assert placed.status_code == 201, placed.text
    assert placed.json()["total"] == 1130
    assert placed.json()["source"] == "cart"

    emptied = await client.get("/api/v1/cart", headers=guest)
    assert emptied.json()["items"] == []
    taken = await _stock(client, auth_headers, product["id"])
    assert taken["quantity"] == 1
    assert taken["status"] == "available"


async def test_cancel_restores_stock_once(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Limited gown", price=800, quantity=2)
    placed = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 2}],
            **SHIPPING,
        },
    )
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]
    sold = await _stock(client, auth_headers, product["id"])
    assert sold["quantity"] == 0
    assert sold["status"] == "sold-out"

    cancelled = await client.patch(
        f"/api/v1/admin/orders/{order_id}",
        headers=auth_headers,
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    restored = await _stock(client, auth_headers, product["id"])
    assert restored["quantity"] == 2
    assert restored["status"] == "available"

    again = await client.patch(
        f"/api/v1/admin/orders/{order_id}",
        headers=auth_headers,
        json={"status": "cancelled", "courier_name": "Sundarban"},
    )
    assert again.status_code == 200
    still = await _stock(client, auth_headers, product["id"])
    assert still["quantity"] == 2

    hidden = await client.get("/api/v1/admin/orders")
    assert hidden.status_code == 401


async def test_public_lookup_needs_the_order_phone(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Lookup gown", price=900, quantity=3)
    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
        },
    )
    assert placed.status_code == 201, placed.text
    number = placed.json()["number"]

    found = await client.post(
        "/api/v1/orders/lookup",
        json={"number": number.lower(), "phone": "01700-000000"},
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["number"] == number
    assert re.fullmatch(r"IM-[0-9A-F]{8}", number)
    assert body["status"] == "new"
    assert body["phone"] == "017••••000"
    assert body["total"] == body["subtotal"] + body["shipping"]
    assert body["items"][0]["title"] == "Lookup gown"
    assert "id" not in body
    assert "anonymous" not in body
    assert "address" not in body
    assert "notes" not in body
    assert "email" not in body
    assert "district" not in body
    assert "area" not in body
    assert "id" not in body["items"][0]

    wrong = await client.post(
        "/api/v1/orders/lookup",
        json={"number": number, "phone": "01800000000"},
    )
    missing = await client.post(
        "/api/v1/orders/lookup",
        json={"number": "IM-00000000", "phone": "01700000000"},
    )
    assert wrong.status_code == 404
    assert missing.status_code == 404
    assert wrong.json()["error"]["message"] == missing.json()["error"]["message"]

    bad = await client.post(
        "/api/v1/orders/lookup",
        json={"number": "IM-1001", "phone": "01700000000"},
    )
    assert bad.status_code == 422
