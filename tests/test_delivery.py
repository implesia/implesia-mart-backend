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


async def _login(client: AsyncClient, auth_headers: dict[str, str], role: str) -> dict[str, str]:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": f"{role}@implesia.com",
            "full_name": role,
            "password": f"{role}-passphrase",
            "role": role,
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": f"{role}@implesia.com", "password": f"{role}-passphrase"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_public_rates_default_and_admin_updates_them(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    public = await client.get("/api/v1/delivery")
    assert public.status_code == 200
    assert public.json() == {
        "inside_dhaka": 70,
        "dhaka_suburban": 100,
        "outside_dhaka": 130,
    }
    assert public.headers["cache-control"] == "public, max-age=60"

    anonymous = await client.patch(
        "/api/v1/admin/delivery",
        json={"inside_dhaka": 80, "dhaka_suburban": 100, "outside_dhaka": 120},
    )
    assert anonymous.status_code == 401

    viewer = await _login(client, auth_headers, "viewer")
    seen = await client.get("/api/v1/admin/delivery", headers=viewer)
    assert seen.status_code == 200
    denied = await client.patch(
        "/api/v1/admin/delivery",
        headers=viewer,
        json={"inside_dhaka": 80, "dhaka_suburban": 100, "outside_dhaka": 120},
    )
    assert denied.status_code == 403

    editor = await _login(client, auth_headers, "editor")
    extra = await client.patch(
        "/api/v1/admin/delivery",
        headers=editor,
        json={"inside_dhaka": 80, "dhaka_suburban": 100, "outside_dhaka": 120, "total": 1},
    )
    assert extra.status_code == 422
    negative = await client.patch(
        "/api/v1/admin/delivery",
        headers=editor,
        json={"inside_dhaka": -1, "dhaka_suburban": 100, "outside_dhaka": 120},
    )
    assert negative.status_code == 422

    saved = await client.patch(
        "/api/v1/admin/delivery",
        headers=editor,
        json={"inside_dhaka": 80, "dhaka_suburban": 100, "outside_dhaka": 120},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"inside_dhaka": 80, "dhaka_suburban": 100, "outside_dhaka": 120}
    assert saved.headers["cache-control"] == "no-store"

    again = await client.get("/api/v1/delivery")
    assert again.json() == {"inside_dhaka": 80, "dhaka_suburban": 100, "outside_dhaka": 120}


async def test_checkout_and_cart_use_the_saved_rates(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.patch(
        "/api/v1/admin/delivery",
        headers=auth_headers,
        json={"inside_dhaka": 80, "dhaka_suburban": 100, "outside_dhaka": 120},
    )
    assert saved.status_code == 200, saved.text

    product = await _create(client, auth_headers, price=1000, quantity=4)
    added = await client.post(
        "/api/v1/cart/items",
        headers=auth_headers,
        json={"product_id": product["id"], "quantity": 2},
    )
    assert added.status_code == 200, added.text
    cart = added.json()
    assert cart["inside_dhaka"] == 80
    assert cart["dhaka_suburban"] == 100
    assert cart["outside_dhaka"] == 120
    assert cart["shipping"] == 0
    assert cart["total"] == cart["subtotal"]

    inside = await client.post(
        "/api/v1/orders/quote",
        headers=auth_headers,
        json={
            "source": "direct",
            "district": "Dhaka",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert inside.status_code == 200, inside.text
    assert inside.json()["delivery_zone"] == "inside"
    assert inside.json()["shipping"] == 80
    assert inside.json()["total"] == 1080

    outside = await client.post(
        "/api/v1/orders/quote",
        headers=auth_headers,
        json={
            "source": "direct",
            "district": SHIPPING["district"],
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert outside.status_code == 200, outside.text
    assert outside.json()["delivery_zone"] == "outside"
    assert outside.json()["shipping"] == 120

    suburban = await client.post(
        "/api/v1/orders/quote",
        headers=auth_headers,
        json={
            "source": "direct",
            "district": "ঢাকা",
            "area": "সাভার",
            "delivery_zone": "inside",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert suburban.status_code == 200, suburban.text
    assert suburban.json()["delivery_zone"] == "suburban"
    assert suburban.json()["shipping"] == 100

    named = await client.post(
        "/api/v1/orders/quote",
        headers=auth_headers,
        json={
            "source": "direct",
            "district": "সাভার",
            "area": "বাইপাইল",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert named.status_code == 200, named.text
    assert named.json()["delivery_zone"] == "suburban"
    assert named.json()["shipping"] == 100

    chosen = await client.post(
        "/api/v1/orders/quote",
        headers=auth_headers,
        json={
            "source": "direct",
            "district": "ঢাকা",
            "area": "ধানমন্ডি",
            "delivery_zone": "suburban",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["delivery_zone"] == "suburban"
    assert chosen.json()["shipping"] == 100

    other_nawabganj = await client.post(
        "/api/v1/orders/quote",
        headers=auth_headers,
        json={
            "source": "direct",
            "district": "চাঁপাইনবাবগঞ্জ",
            "area": "নবাবগঞ্জ",
            "delivery_zone": "inside",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert other_nawabganj.status_code == 200, other_nawabganj.text
    assert other_nawabganj.json()["delivery_zone"] == "outside"
    assert other_nawabganj.json()["shipping"] == 120

    same = await client.patch(
        "/api/v1/admin/delivery",
        headers=auth_headers,
        json={"inside_dhaka": 90, "dhaka_suburban": 90, "outside_dhaka": 90},
    )
    assert same.status_code == 200
    refreshed = await client.get("/api/v1/cart", headers=auth_headers)
    assert refreshed.json()["shipping"] == 90
    assert refreshed.json()["total"] == refreshed.json()["subtotal"] + 90
