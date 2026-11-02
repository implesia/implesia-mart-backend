from decimal import Decimal

from httpx import AsyncClient

from app.schemas.pricing import QuantityTier
from app.services import pricing_service as pricing
from tests.test_orders import SHIPPING, _key
from tests.test_products import _create, _parts

DEFAULTS = pricing.default_tiers()
RULES = pricing.Rules(tiers=DEFAULTS, max_percent=Decimal(90))


def _line(regular: int, base: str, quantity: int, rules: pricing.Rules = RULES) -> pricing.Line:
    price = pricing.selling_price(regular, Decimal(base))
    return pricing.price_line(
        regular=regular,
        price=price,
        stored_base=pricing.to_hundredths(Decimal(base)),
        quantity=quantity,
        tiers=rules.tiers,
        rules=rules,
    )


def test_base_discount_gives_the_quantity_one_price() -> None:
    line = _line(1000, "28", 1)
    assert line.unit_price == 720
    assert line.total_percent == Decimal("28.00")
    assert line.quantity_percent == Decimal("0.00")


def test_eight_units_add_two_percent_on_the_regular_price() -> None:
    line = _line(1000, "28", 8)
    assert line.total_percent == Decimal("30.00")
    assert line.quantity_percent == Decimal("2.00")
    assert line.unit_price == 700
    assert line.line_total == 5600
    # Beyond the last tier the extra stays at +2 %.
    assert _line(1000, "28", 20).total_percent == Decimal("30.00")


def test_each_default_tier() -> None:
    expected = {1: "28", 2: "28.25", 3: "28.5", 4: "28.75", 5: "29", 6: "29.25", 7: "29.5"}
    for quantity, total in expected.items():
        assert _line(1000, "28", quantity).total_percent == Decimal(total), quantity
    # 0.25 % of 1000 is 2.5 taka: rounded half up to 3.
    assert _line(1000, "28", 2).unit_price == 717


def test_cap_limits_the_total_and_never_reaches_100() -> None:
    capped = pricing.Rules(tiers=DEFAULTS, max_percent=Decimal("29"))
    assert _line(1000, "28", 8, capped).total_percent == Decimal("29.00")
    assert _line(1000, "28", 8, capped).unit_price == 710
    # A cap below the base discount wins over the base.
    low = pricing.Rules(tiers=DEFAULTS, max_percent=Decimal("20"))
    assert _line(1000, "28", 1, low).unit_price == 800
    # Even a 99.99 % cap and a huge tier stay below 100 %.
    greedy = pricing.Rules(
        tiers=(QuantityTier(min_quantity=2, extra_percent=Decimal("99.99")),),
        max_percent=Decimal("99.99"),
    )
    line = _line(1000, "50", 2, greedy)
    assert line.total_percent == Decimal("99.99")
    assert line.unit_price >= 0


def test_tiers_switched_off_and_custom_tiers() -> None:
    off = pricing.Rules(tiers=(), max_percent=Decimal(90), tiers_enabled=False)
    assert _line(1000, "28", 8, off).unit_price == 720
    custom = (QuantityTier(min_quantity=3, extra_percent=Decimal("5")),)
    line = pricing.price_line(
        regular=1000, price=720, stored_base=2800, quantity=3, tiers=custom, rules=off
    )
    assert line.total_percent == Decimal("33.00")
    assert line.unit_price == 670


def test_older_prices_keep_their_quantity_one_price() -> None:
    # No saved base %: derived from price/compare_at, the stored price stays exact.
    line = pricing.price_line(
        regular=999, price=777, stored_base=None, quantity=1, tiers=DEFAULTS, rules=RULES
    )
    assert line.unit_price == 777
    assert line.base_percent == Decimal("22.22")
    plain = pricing.price_line(
        regular=15000, price=15000, stored_base=None, quantity=1, tiers=DEFAULTS, rules=RULES
    )
    assert plain.unit_price == 15000
    assert plain.total_percent == Decimal("0.00")


async def test_admin_pricing_settings(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    anonymous = await client.get("/api/v1/admin/pricing")
    assert anonymous.status_code == 401
    seen = await client.get("/api/v1/admin/pricing", headers=auth_headers)
    assert seen.status_code == 200, seen.text
    assert seen.headers["cache-control"] == "no-store"
    body = seen.json()
    assert body["tiers_enabled"] is True
    assert body["max_discount_percent"] == 90
    assert body["tiers"][-1] == {"min_quantity": 8, "extra_percent": 2.0}

    duplicate = await client.put(
        "/api/v1/admin/pricing",
        headers=auth_headers,
        json={
            "tiers_enabled": True,
            "max_discount_percent": 50,
            "tiers": [
                {"min_quantity": 2, "extra_percent": 1},
                {"min_quantity": 2, "extra_percent": 2},
            ],
        },
    )
    assert duplicate.status_code == 422
    hundred = await client.put(
        "/api/v1/admin/pricing",
        headers=auth_headers,
        json={"tiers_enabled": True, "max_discount_percent": 100, "tiers": []},
    )
    assert hundred.status_code == 422

    saved = await client.put(
        "/api/v1/admin/pricing",
        headers=auth_headers,
        json={
            "tiers_enabled": False,
            "max_discount_percent": 45.5,
            "tiers": [
                {"min_quantity": 4, "extra_percent": 1.5},
                {"min_quantity": 2, "extra_percent": 0.5},
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "tiers_enabled": False,
        "max_discount_percent": 45.5,
        "tiers": [
            {"min_quantity": 2, "extra_percent": 0.5},
            {"min_quantity": 4, "extra_percent": 1.5},
        ],
    }


async def test_product_regular_price_and_base_discount(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(
        client, auth_headers, regular_price=1000, base_discount_percent=28, quantity=10
    )
    assert product["price"] == 720
    assert product["compare_at_price"] == 1000
    assert product["regular_price"] == 1000
    assert product["base_discount_percent"] == 28
    assert product["tier_mode"] == "global"

    public = await client.get(f"/api/v1/products/by-slug/{product['slug']}")
    assert public.status_code == 200, public.text
    pricing_body = public.json()["pricing"]
    assert pricing_body["regular_price"] == 1000
    assert pricing_body["selling_price"] == 720
    assert pricing_body["base_discount_percent"] == 28
    assert pricing_body["tiers"][0] == {"min_quantity": 2, "extra_percent": 0.25}

    too_much = await client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=auth_headers,
        files=_parts({"base_discount_percent": 95}),
    )
    assert too_much.status_code == 422

    custom = await client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=auth_headers,
        files=_parts(
            {
                "base_discount_percent": 10,
                "tier_mode": "custom",
                "tiers": [{"min_quantity": 3, "extra_percent": 5}],
            }
        ),
    )
    assert custom.status_code == 200, custom.text
    assert custom.json()["price"] == 900
    assert custom.json()["regular_price"] == 1000
    assert custom.json()["tiers"] == [{"min_quantity": 3, "extra_percent": 5.0}]

    added = await client.post(
        "/api/v1/cart/items", json={"product_id": product["id"], "quantity": 3}
    )
    assert added.status_code == 200, added.text
    line = added.json()["items"][0]
    assert line["unit_price"] == 850
    assert line["line_total"] == 2550
    assert line["total_discount_percent"] == 15
    assert line["regular_price"] == 1000

    odd = await client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=auth_headers,
        files=_parts({"base_discount_percent": 28.33}),
    )
    assert odd.json()["price"] == 717
    # A form that re-sends the prices it was shown keeps the saved base %.
    same = await client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=auth_headers,
        files=_parts({"price": 717, "compare_at_price": 1000}),
    )
    assert same.json()["base_discount_percent"] == 28.33
    moved = await client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=auth_headers,
        files=_parts({"price": 700, "compare_at_price": 1000}),
    )
    assert moved.json()["base_discount_percent"] == 30


async def test_order_keeps_its_price_snapshot(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(
        client, auth_headers, regular_price=1000, base_discount_percent=28, quantity=10
    )
    order = {
        "source": "direct",
        "items": [{"product_id": product["id"], "quantity": 4}],
        **SHIPPING,
    }
    quoted = await client.post(
        "/api/v1/orders/quote",
        json={"source": "direct", "items": order["items"], "district": SHIPPING["district"]},
    )
    assert quoted.status_code == 200, quoted.text
    assert quoted.json()["items"][0]["unit_price"] == 712  # 28.75 % off 1000, rounded

    placed = await client.post("/api/v1/orders", headers={"Idempotency-Key": _key()}, json=order)
    assert placed.status_code == 201, placed.text
    item = placed.json()["items"][0]
    assert item["regular_price"] == 1000
    assert item["base_discount_percent"] == 28
    assert item["quantity_discount_percent"] == 0.75
    assert item["total_discount_percent"] == 28.75
    assert item["unit_price"] == 712
    assert item["line_total"] == 2848

    # Changing the rules later does not touch the order already placed.
    changed = await client.put(
        "/api/v1/admin/pricing",
        headers=auth_headers,
        json={"tiers_enabled": False, "max_discount_percent": 10, "tiers": []},
    )
    assert changed.status_code == 200, changed.text
    stored = await client.get(f"/api/v1/admin/orders/{placed.json()['id']}", headers=auth_headers)
    assert stored.status_code == 200, stored.text
    kept = stored.json()["items"][0]
    assert kept["unit_price"] == 712
    assert kept["total_discount_percent"] == 28.75
    assert stored.json()["subtotal"] == 2848
