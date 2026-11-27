"""Phase 27: Weight-based delivery charge system (Bangladesh courier slab model)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.services import delivery_service
from tests.test_products import _create

DHAKA_SHIPPING = {
    "customer_name": "Tariq Hasan",
    "phone": "01711223344",
    "email": "",
    "district": "Dhaka",
    "area": "Dhanmondi",
    "address": "House 10, Road 5",
    "notes": "",
}

OUTSIDE_SHIPPING = {
    "customer_name": "Rina Akter",
    "phone": "01755667788",
    "email": "",
    "district": "Chattogram",
    "area": "Agrabad",
    "address": "House 12, Road 4",
    "notes": "",
}


def _key() -> str:
    return uuid.uuid4().hex


@pytest.mark.parametrize(
    ("weight_grams", "zone", "expected_total", "expected_base", "expected_extra", "expected_steps"),
    [
        (400, "inside", 70, 70, 0, 0),
        (1000, "inside", 70, 70, 0, 0),
        (1001, "inside", 90, 70, 20, 1),
        (2000, "inside", 90, 70, 20, 1),
        (2001, "inside", 110, 70, 40, 2),
        (1000, "suburban", 100, 100, 0, 0),
        (1001, "suburban", 120, 100, 20, 1),
        (1000, "outside", 130, 130, 0, 0),
        (1001, "outside", 150, 130, 20, 1),
        (2001, "outside", 170, 130, 40, 2),
    ],
)
def test_weight_slab_boundary_calculations(
    weight_grams: int,
    zone: str,
    expected_total: int,
    expected_base: int,
    expected_extra: int,
    expected_steps: int,
) -> None:
    rates = delivery_service.StoreFees(70, 100, 130)
    bd = delivery_service.calculate_weight_shipping(zone, weight_grams, rates)
    assert bd.total_fee == expected_total
    assert bd.base_fee == expected_base
    assert bd.extra_weight_fee == expected_extra
    assert bd.extra_steps == expected_steps
    assert bd.total_weight_grams == weight_grams


def test_weight_pricing_disabled_reverts_to_flat_base_fee() -> None:
    rates = delivery_service.StoreFees(70, 100, 130, weight_pricing_enabled=False)
    bd = delivery_service.calculate_weight_shipping("outside", 4500, rates)
    assert bd.total_fee == 130
    assert bd.base_fee == 130
    assert bd.extra_weight_fee == 0
    assert bd.extra_steps == 0


def test_resolve_item_weight_precedence() -> None:
    rates = delivery_service.StoreFees(70, 100, 130, default_product_weight_grams=500)
    # Variant override wins over product weight and default
    assert delivery_service.resolve_item_weight_grams(400, 850, rates) == 850
    # Product weight wins over default when variant has no override
    assert delivery_service.resolve_item_weight_grams(400, None, rates) == 400
    # Legacy NULL product falls back to store default (500g)
    assert delivery_service.resolve_item_weight_grams(None, None, rates) == 500


async def test_multi_item_aggregation_not_per_item_base_fee(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # 3 x 400g = 1200g -> Inside Dhaka: 70 base + 1 extra step (20) = 90 (NOT 3 x 70)
    p = await _create(
        client,
        auth_headers,
        title="400g Mug",
        slug="mug-400g",
        price=500,
        quantity=10,
        weight_grams=400,
    )
    quote_res = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "items": [{"product_id": p["id"], "quantity": 3}],
            "district": "Dhaka",
            "area": "Dhanmondi",
        },
    )
    assert quote_res.status_code == 200, quote_res.text
    q = quote_res.json()
    assert q["total_weight_grams"] == 1200
    assert q["base_shipping"] == 70
    assert q["extra_weight_steps"] == 1
    assert q["extra_weight_shipping"] == 20
    assert q["shipping"] == 90
    assert q["total"] == q["subtotal"] + 90

    # Place the order and confirm weight snapshot on order & order_items
    order_res = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": p["id"], "quantity": 3}],
            **DHAKA_SHIPPING,
        },
    )
    assert order_res.status_code == 201, order_res.text
    order = order_res.json()
    assert order["shipping"] == 90
    assert order["total_weight_grams"] == 1200
    assert order["items"][0]["unit_weight_grams"] == 400


async def test_variant_weight_override_and_legacy_null_fallback_and_packaging_tare(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    # Enable 100g packaging tare weight via admin delivery settings
    upd = await client.patch(
        "/api/v1/admin/delivery",
        headers=auth_headers,
        json={
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
            "extra_fee_outside": 25,
            "packaging_weight_grams": 100,
            "default_product_weight_grams": 500,
        },
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["packaging_weight_grams"] == 100
    assert upd.json()["extra_fee_outside"] == 25

    # Product with variant weight override (1200g) vs base product weight (400g)
    var_prod = await _create(
        client,
        auth_headers,
        title="Weighted Bottle",
        slug="weighted-bottle",
        price=1000,
        weight_grams=400,
        content={
            "tagline": "Steel",
            "description": "Insulated bottle",
            "unit_label": "",
            "image_alt": "Bottle",
            "options": [
                {
                    "id": "opt-size",
                    "name": "Size",
                    "kind": "size",
                    "values": [
                        {"id": "val-500ml", "label": "500ml"},
                        {"id": "val-2l", "label": "2L"},
                    ],
                }
            ],
        },
        variants=[
            {
                "options": {"opt-size": "val-500ml"},
                "sku": "BOT-500",
                "price": 1000,
                "quantity": 5,
            },
            {
                "options": {"opt-size": "val-2l"},
                "sku": "BOT-2L",
                "price": 1800,
                "quantity": 5,
                "weight_grams": 1200,
            },
        ],
    )
    heavy_variant = next(v for v in var_prod["variants"] if v["sku"] == "BOT-2L")
    assert heavy_variant["weight_grams"] == 1200

    # Legacy product with NULL weight_grams in DB (falls back to 500g)
    legacy_prod = await _create(
        client,
        auth_headers,
        title="Legacy Item",
        slug="legacy-item-null-weight",
        price=600,
        quantity=10,
        weight_grams=500,
    )
    await db_session.execute(
        update(Product).where(Product.id == uuid.UUID(legacy_prod["id"])).values(weight_grams=None)
    )
    await db_session.commit()

    # Admin missing_weight=true filter returns ONLY the legacy NULL-weight product
    missing_res = await client.get(
        "/api/v1/admin/products?missing_weight=true",
        headers=auth_headers,
    )
    assert missing_res.status_code == 200, missing_res.text
    missing_ids = [item["id"] for item in missing_res.json()["items"]]
    assert legacy_prod["id"] in missing_ids
    assert var_prod["id"] not in missing_ids

    # Quote: 1x heavy variant (1200g) + 2x legacy NULL (1000g) + 100g tare = 2300g
    # Outside Dhaka: base 130 (<= 1000g) + ceil((2300 - 1000)/1000)=2 steps x 25 = 180
    quote_res = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "items": [
                {"product_id": var_prod["id"], "variant_id": heavy_variant["id"], "quantity": 1},
                {"product_id": legacy_prod["id"], "quantity": 2},
            ],
            "district": "Chattogram",
            "area": "Agrabad",
        },
    )
    assert quote_res.status_code == 200, quote_res.text
    q = quote_res.json()
    assert q["total_weight_grams"] == 2300
    assert q["base_shipping"] == 130
    assert q["extra_weight_steps"] == 2
    assert q["extra_weight_shipping"] == 50
    assert q["shipping"] == 180

    # Master toggle OFF reverts to flat base fee (130)
    off = await client.patch(
        "/api/v1/admin/delivery",
        headers=auth_headers,
        json={
            "inside_dhaka": 70,
            "dhaka_suburban": 100,
            "outside_dhaka": 130,
            "inside_enabled": True,
            "suburban_enabled": True,
            "outside_enabled": True,
            "weight_pricing_enabled": False,
        },
    )
    assert off.status_code == 200
    flat_quote = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "items": [
                {"product_id": var_prod["id"], "variant_id": heavy_variant["id"], "quantity": 1},
                {"product_id": legacy_prod["id"], "quantity": 2},
            ],
            "district": "Chattogram",
            "area": "Agrabad",
        },
    )
    assert flat_quote.status_code == 200
    assert flat_quote.json()["shipping"] == 130
    assert flat_quote.json()["extra_weight_shipping"] == 0


async def test_product_create_requires_positive_weight_grams(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    import json

    from tests.test_products import _parts, _product

    missing_weight = _product(title="No Weight", slug="no-weight-item")
    missing_weight.pop("weight_grams", None)
    res = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(missing_weight),
    )
    assert res.status_code == 400, res.text

    zero_weight = _product(title="Zero Weight", slug="zero-weight-item", weight_grams=0)
    res2 = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(zero_weight),
    )
    assert res2.status_code == 400, res2.text

    # Existing product PATCH without weight_grams still succeeds (legacy edits don't break)
    ok = await _create(
        client, auth_headers, title="Editable Item", slug="editable-item-w", weight_grams=350
    )
    patched = await client.patch(
        f"/api/v1/admin/products/{ok['id']}",
        headers=auth_headers,
        files=[("payload", (None, json.dumps({"title": "Editable Item Renamed"})))],
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["weight_grams"] == 350
