import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import Cart, CartItem
from app.models.user import User
from tests.test_products import _create


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _guest(token: str) -> dict[str, str]:
    return {"X-Cart-Token": token}


async def test_add_to_cart_uses_the_server_price(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=15000, quantity=4)
    added = await client.post(
        "/api/v1/cart/items",
        headers=auth_headers,
        json={"product_id": product["id"], "quantity": 2, "unit_price": 1},
    )
    assert added.status_code == 422

    added = await client.post(
        "/api/v1/cart/items",
        json={"product_id": product["id"], "quantity": 2},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["anonymous"] is True
    token = body["cart_token"]
    assert token
    assert body["item_count"] == 2
    assert body["items"][0]["unit_price"] == 15000
    assert body["items"][0]["line_total"] == 30000
    assert body["subtotal"] == 30000
    assert body["shipping"] == 0
    assert body["total"] == 30000

    again = await client.post(
        "/api/v1/cart/items",
        headers=_guest(token),
        json={"product_id": product["id"], "quantity": 1},
    )
    assert again.status_code == 200
    assert again.json()["items"][0]["quantity"] == 3


async def test_anonymous_cart_stays_private(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Guest gown", price=500, quantity=5)
    added = await client.post(
        "/api/v1/cart/items",
        json={"product_id": product["id"], "quantity": 2},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    token = body["cart_token"]
    assert body["anonymous"] is True
    assert token
    assert body["items"][0]["quantity"] == 2
    assert "guest_token" not in added.text

    stranger = await client.get("/api/v1/cart", headers=_guest("b" * 32))
    assert stranger.status_code == 200
    assert stranger.json()["items"] == []
    assert stranger.json()["id"] is None

    mine = await client.get("/api/v1/cart", headers=_guest(token))
    assert mine.json()["id"] == body["id"]
    assert mine.json()["items"][0]["quantity"] == 2

    stolen = await client.delete(
        f"/api/v1/cart/items/{body['items'][0]['id']}",
        headers=_guest("c" * 32),
    )
    assert stolen.status_code == 404


async def test_an_admin_token_does_not_claim_the_shopper_cart(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Merge gown", price=800, quantity=5)
    added = await client.post(
        "/api/v1/cart/items",
        json={"product_id": product["id"], "quantity": 2},
    )
    token = added.json()["cart_token"]
    claimed = await client.get("/api/v1/cart", headers={**auth_headers, **_guest(token)})
    assert claimed.status_code == 200, claimed.text
    body = claimed.json()
    assert body["anonymous"] is True
    assert body["cart_token"] == token
    assert body["items"][0]["quantity"] == 2

    staff = await client.get("/api/v1/cart", headers=auth_headers)
    assert staff.json()["items"] == []

    still = await client.get("/api/v1/cart", headers=_guest(token))
    assert still.json()["items"][0]["quantity"] == 2


async def test_dashboard_lists_logged_in_and_anonymous_carts(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    gown = await _create(client, auth_headers, title="Listed gown", price=1000, quantity=5)
    lamp = await _create(client, auth_headers, title="Listed lamp", price=400, quantity=5)

    owner = await db_session.scalar(select(User).where(User.email == "admin@implesia.com"))
    assert owner is not None
    owned = Cart(user_id=owner.id)
    owned.items.append(
        CartItem(product_id=uuid.UUID(gown["id"]), quantity=1, selection=[])
    )
    db_session.add(owned)
    await db_session.commit()
    guest_cart = await client.post(
        "/api/v1/cart/items",
        json={"product_id": lamp["id"], "quantity": 3},
    )
    assert guest_cart.status_code == 200, guest_cart.text

    listed = await client.get("/api/v1/admin/carts", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    kinds = {item["owner"]["kind"] for item in body["items"]}
    assert {"user", "guest"} <= kinds
    guest = next(item for item in body["items"] if item["owner"]["kind"] == "guest")
    assert guest["owner"]["email"] is None
    assert guest["items"][0]["title"] == "Listed lamp"
    assert guest["items"][0]["quantity"] == 3
    assert "cart_token" not in listed.text
    assert body["metrics"]["guest_carts"] >= 1
    assert body["metrics"]["user_carts"] >= 1

    detail = await client.get(f"/api/v1/admin/carts/{guest['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["items"][0]["quantity"] == 3

    hidden = await client.get(
        "/api/v1/admin/carts",
        headers=auth_headers,
        params={"q": "Listed lamp", "owner": "guest"},
    )
    assert [item["id"] for item in hidden.json()["items"]] == [guest["id"]]

    anonymous = await client.get("/api/v1/admin/carts")
    assert anonymous.status_code == 401
