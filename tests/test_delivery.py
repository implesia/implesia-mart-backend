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
        "inside_enabled": True,
        "suburban_enabled": True,
        "outside_enabled": True,
        "weight_pricing_enabled": True,
        "base_weight_grams": 1000,
        "extra_weight_step_grams": 1000,
        "extra_fee_inside": 20,
        "extra_fee_suburban": 20,
        "extra_fee_outside": 20,
        "packaging_weight_grams": 0,
        "default_product_weight_grams": 500,
        "suburban_places": ["Savar", "Ashulia", "Gazipur", "Keraniganj", "Narayanganj"],
    }
    assert public.headers["cache-control"] == "public, max-age=60"

    anonymous = await client.patch(
        "/api/v1/admin/delivery",
        json={
            "inside_dhaka": 80,
            "dhaka_suburban": 100,
            "outside_dhaka": 120,
            "inside_enabled": True,
            "suburban_enabled": True,
            "outside_enabled": True,
        },
    )
    assert anonymous.status_code == 401

    viewer = await _login(client, auth_headers, "viewer")
    seen = await client.get("/api/v1/admin/delivery", headers=viewer)
    assert seen.status_code == 200
    denied = await client.patch(
        "/api/v1/admin/delivery",
        headers=viewer,
        json={
            "inside_dhaka": 80,
            "dhaka_suburban": 100,
            "outside_dhaka": 120,
            "inside_enabled": True,
            "suburban_enabled": True,
            "outside_enabled": True,
        },
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
        json={
            "inside_dhaka": 80,
            "dhaka_suburban": 100,
            "outside_dhaka": 120,
            "inside_enabled": True,
            "suburban_enabled": True,
            "outside_enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "inside_dhaka": 80,
        "dhaka_suburban": 100,
        "outside_dhaka": 120,
        "inside_enabled": True,
        "suburban_enabled": True,
        "outside_enabled": True,
        "weight_pricing_enabled": True,
        "base_weight_grams": 1000,
        "extra_weight_step_grams": 1000,
        "extra_fee_inside": 20,
        "extra_fee_suburban": 20,
        "extra_fee_outside": 20,
        "packaging_weight_grams": 0,
        "default_product_weight_grams": 500,
        "suburban_places": ["Savar", "Ashulia", "Gazipur", "Keraniganj", "Narayanganj"],
    }
    assert saved.headers["cache-control"] == "no-store"

    again = await client.get("/api/v1/delivery")
    assert again.json() == saved.json()


async def test_checkout_and_cart_use_the_saved_rates(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.patch(
        "/api/v1/admin/delivery",
        headers=auth_headers,
        json={
            "inside_dhaka": 80,
            "dhaka_suburban": 100,
            "outside_dhaka": 120,
            "inside_enabled": True,
            "suburban_enabled": True,
            "outside_enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text

    product = await _create(client, auth_headers, price=1000, quantity=4)
    added = await client.post(
        "/api/v1/cart/items",
        json={"product_id": product["id"], "quantity": 2},
    )
    assert added.status_code == 200, added.text
    cart = added.json()
    guest = {"X-Cart-Token": cart["cart_token"]}
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
        json={
            "inside_dhaka": 90,
            "dhaka_suburban": 90,
            "outside_dhaka": 90,
            "inside_enabled": True,
            "suburban_enabled": True,
            "outside_enabled": True,
        },
    )
    assert same.status_code == 200
    refreshed = await client.get("/api/v1/cart", headers=guest)
    assert refreshed.json()["shipping"] == 90
    assert refreshed.json()["total"] == refreshed.json()["subtotal"] + 90


async def test_a_zone_or_every_zone_can_be_turned_off(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=3)
    flags = {
        "inside_dhaka": 70,
        "dhaka_suburban": 100,
        "outside_dhaka": 130,
        "inside_enabled": True,
        "suburban_enabled": False,
        "outside_enabled": True,
    }
    saved = await client.patch("/api/v1/admin/delivery", headers=auth_headers, json=flags)
    assert saved.status_code == 200, saved.text
    assert saved.json()["suburban_enabled"] is False

    city = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "ঢাকা",
            "area": "ধানমন্ডি",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert city.status_code == 200, city.text
    assert city.json()["delivery_available"] is True
    assert city.json()["delivery_zone"] == "inside"
    assert city.json()["shipping"] == 70

    farther = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "ঢাকা",
            "area": "সাভার",
            "delivery_zone": "suburban",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert farther.status_code == 200, farther.text
    assert farther.json()["delivery_available"] is True
    assert farther.json()["delivery_zone"] == "outside"
    assert farther.json()["shipping"] == 130

    closed = await client.patch(
        "/api/v1/admin/delivery",
        headers=auth_headers,
        json={**flags, "inside_enabled": False, "outside_enabled": False},
    )
    assert closed.status_code == 200, closed.text
    blocked = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "ঢাকা",
            "area": "সাভার",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["delivery_available"] is False
    assert blocked.json()["shipping"] == 0
    assert blocked.json()["total"] == blocked.json()["subtotal"]

    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "delivery-off"},
        json={
            "source": "direct",
            "district": "ঢাকা",
            "area": "সাভার",
            "customer_name": "Rina Akter",
            "phone": "01700000000",
            "email": "",
            "address": "House 12, Savar",
            "notes": "",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert placed.status_code == 422, placed.text


async def test_dynamic_suburban_places_can_be_configured_from_admin(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=5, weight_grams=400)

    # Default Steadfast 5 places (including Gazipur & Narayanganj in English and Bangla) -> suburban
    for district, area in (
        ("Savar", ""),
        ("Dhaka", "Ashulia"),
        ("Gazipur", ""),
        ("গাজীপুর", ""),
        ("Keraniganj", ""),
        ("Narayanganj", ""),
        ("নারায়ণগঞ্জ", ""),
    ):
        res = await client.post(
            "/api/v1/orders/quote",
            json={
                "source": "direct",
                "district": district,
                "area": area,
                "items": [{"product_id": product["id"], "quantity": 1}],
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["delivery_zone"] == "suburban", (district, area, res.json())
        assert res.json()["shipping"] == 100

    # Munshiganj is outside by default
    before = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "Munshiganj",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert before.status_code == 200
    assert before.json()["delivery_zone"] == "outside"

    # Admin dynamically adds Munshiganj and removes Gazipur
    updated = await client.patch(
        "/api/v1/admin/delivery",
        headers=auth_headers,
        json={
            "inside_dhaka": 70,
            "dhaka_suburban": 100,
            "outside_dhaka": 130,
            "inside_enabled": True,
            "suburban_enabled": True,
            "outside_enabled": True,
            "suburban_places": ["Savar", "Ashulia", "Keraniganj", "Narayanganj", "Munshiganj"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["suburban_places"] == [
        "Savar",
        "Ashulia",
        "Keraniganj",
        "Narayanganj",
        "Munshiganj",
    ]

    # Munshiganj (and its Bangla alias) now resolves to suburban
    after_add = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "মুন্সীগঞ্জ",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert after_add.status_code == 200
    assert after_add.json()["delivery_zone"] == "suburban"
    assert after_add.json()["shipping"] == 100

    # Gazipur was removed -> now resolves to outside
    after_remove = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "Gazipur",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert after_remove.status_code == 200
    assert after_remove.json()["delivery_zone"] == "outside"
    assert after_remove.json()["shipping"] == 130
