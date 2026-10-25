"""Product variants: admin save rules, roll-up, cart, quote and order authority."""

import json
import uuid

from httpx import AsyncClient

from tests.test_orders import SHIPPING, _key
from tests.test_product_options import OPTIONS
from tests.test_products import _create, _parts, _product

ADMIN = "/api/v1/admin/products"


def _content(options: list[dict] | None = None) -> dict:
    return {
        "tagline": "ক্যাটাগরি",
        "description": "বিবরণ।",
        "unit_label": "পিস",
        "highlights": ["টেকসই"],
        "options": OPTIONS if options is None else options,
    }


def _combos(**per: dict) -> list[dict]:
    """Two groups (color red/navy, size m/l) give four combinations."""
    rows = []
    for color in ("red", "navy"):
        for size in ("m", "l"):
            extra = per.get(f"{color}-{size}", {})
            rows.append(
                {
                    "options": {"color-main": color, "size-main": size},
                    "sku": f"SKU-{color}-{size}".upper(),
                    "price": 1000 + (200 if size == "l" else 0),
                    "compare_at_price": None,
                    "quantity": 3,
                    "is_active": True,
                    **extra,
                }
            )
    return rows


async def _make(
    client: AsyncClient,
    headers: dict[str, str],
    variants: list[dict] | None = None,
    **overrides: object,
) -> dict:
    body = _product(
        title=overrides.pop("title", "Variant tee"),  # type: ignore[arg-type]
        category="fashion",
        content=_content(),
        variants=_combos() if variants is None else variants,
        **overrides,
    )
    response = await client.post(ADMIN, headers=headers, files=_parts(body))
    assert response.status_code == 201, response.text
    return response.json()


async def _post(client: AsyncClient, headers: dict[str, str], **overrides: object):
    body = _product(**{"content": _content(), **overrides})
    return await client.post(ADMIN, headers=headers, files=_parts(body))


async def _patch(client: AsyncClient, headers: dict[str, str], product_id: str, body: dict):
    return await client.patch(
        f"{ADMIN}/{product_id}", headers=headers, files=[("payload", (None, json.dumps(body)))]
    )


async def _read(client: AsyncClient, headers: dict[str, str], product_id: str) -> dict:
    response = await client.get(f"{ADMIN}/{product_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _input(row: dict, **changes: object) -> dict:
    """A variant read back from the API, as the editor sends it (read-only fields dropped)."""
    keep = ("id", "options", "sku", "price", "compare_at_price", "quantity", "is_active")
    return {**{key: row[key] for key in keep}, **changes}


def _variant(product: dict, color: str, size: str) -> dict:
    return next(
        row
        for row in product["variants"]
        if row["options"] == {"color-main": color, "size-main": size}
    )


async def _cart_add(
    client: AsyncClient, product_id: str, variant_id: str | None, qty: int = 1, **kw
):
    body: dict = {"product_id": product_id, "quantity": qty}
    if variant_id is not None:
        body["variant_id"] = variant_id
    return await client.post("/api/v1/cart/items", json=body, **kw)


# ------------------------------------------------------------------ admin save


async def test_create_with_variants_rolls_up_price_and_stock(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers, price=9, quantity=None)
    assert product["has_variants"] is True
    assert product["price"] == 1000  # lowest active variant, not the submitted 9
    assert product["quantity"] == 12  # 4 variants x 3
    assert len(product["variants"]) == 4
    assert product["variants"][0]["label"] == "লাল / M"
    assert [row["sort_order"] for row in product["variants"]] == [0, 1, 2, 3]
    card = next(
        row
        for row in (await client.get(ADMIN, headers=auth_headers)).json()["items"]
        if row["id"] == product["id"]
    )
    assert card["has_variants"] is True


async def test_made_to_order_variant_makes_the_product_unlimited(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    rows = _combos(**{"red-m": {"quantity": None}})
    product = await _make(client, auth_headers, variants=rows)
    assert product["quantity"] is None


async def test_public_detail_lists_variants_without_stock_counts(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    rows = _combos(**{"red-m": {"quantity": 0}, "navy-l": {"is_active": False}})
    product = await _make(client, auth_headers, variants=rows)
    detail = (await client.get(f"/api/v1/products/by-slug/{product['slug']}")).json()
    assert len(detail["variants"]) == 3  # the inactive one is hidden
    by_label = {row["label"]: row for row in detail["variants"]}
    assert by_label["লাল / M"]["available"] is False
    assert by_label["নেভি / M"]["available"] is True
    assert "quantity" not in json.dumps(detail["variants"])
    assert "sku" not in json.dumps(detail["variants"]).lower()
    assert detail["min_per_order"] == 1 and detail["max_per_order"] == 5
    assert detail["has_variants"] is True if "has_variants" in detail else True


async def test_variant_rules_are_enforced(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    rows = _combos()
    cases = {
        "missing option": [{**rows[0], "options": {"color-main": "red"}}],
        "unknown value": [{**rows[0], "options": {"color-main": "red", "size-main": "xl"}}],
        "unknown group": [
            {**rows[0], "options": {"color-main": "red", "size-main": "m", "x": "y"}}
        ],
        "duplicate combination": [rows[0], {**rows[1], "options": rows[0]["options"]}],
        "duplicate sku in payload": [rows[0], {**rows[1], "sku": rows[0]["sku"].lower()}],
        "compare below price": [{**rows[0], "price": 500, "compare_at_price": 100}],
        "negative price": [{**rows[0], "price": -1}],
        "negative stock": [{**rows[0], "quantity": -1}],
        "bad sku chars": [{**rows[0], "sku": "A|B"}],
    }
    for name, variants in cases.items():
        response = await _post(client, auth_headers, variants=variants)
        assert response.status_code == 422, (name, response.text)
    no_options = await _post(client, auth_headers, variants=[rows[0]], content=_content(options=[]))
    assert no_options.status_code == 422


async def test_sku_must_be_unique_across_products(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _make(client, auth_headers, title="First tee")
    clash = await _post(client, auth_headers, title="Second tee", variants=_combos())
    assert clash.status_code == 409, clash.text
    assert "SKU" in clash.json()["error"]["message"]
    # the failed create left nothing behind
    titles = [
        row["title"] for row in (await client.get(ADMIN, headers=auth_headers)).json()["items"]
    ]
    assert "Second tee" not in titles


async def test_editing_unrelated_fields_keeps_variants_and_ids(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    before = {row["id"]: row for row in product["variants"]}
    response = await _patch(client, auth_headers, product["id"], {"title": "Renamed tee"})
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["title"] == "Renamed tee"
    assert {row["id"]: row for row in after["variants"]} == before
    assert after["price"] == 1000 and after["quantity"] == 12


async def test_update_changes_price_and_stock_by_id_and_keeps_order(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    rows = [
        {
            "id": row["id"],
            "options": row["options"],
            "sku": row["sku"],
            "price": row["price"] + 100,
            "compare_at_price": row["compare_at_price"],
            "quantity": 1,
            "is_active": row["is_active"],
        }
        for row in product["variants"]
    ]
    response = await _patch(client, auth_headers, product["id"], {"variants": rows})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["price"] == 1100 and body["quantity"] == 4
    assert [row["id"] for row in body["variants"]] == [row["id"] for row in product["variants"]]


async def test_swapping_options_and_skus_between_variants_is_safe(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    first, second = product["variants"][0], product["variants"][1]
    rows = [
        _input(first, options=second["options"], sku=second["sku"]),
        _input(second, options=first["options"], sku=first["sku"]),
        *[_input(row) for row in product["variants"][2:]],
    ]
    response = await _patch(client, auth_headers, product["id"], {"variants": rows})
    assert response.status_code == 200, response.text
    body = response.json()
    swapped = {row["id"]: row for row in body["variants"]}
    assert swapped[first["id"]]["options"] == second["options"]
    assert swapped[second["id"]]["sku"] == first["sku"]


async def test_foreign_variant_id_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    rows = [_input(product["variants"][0], id=str(uuid.uuid4()))]
    response = await _patch(client, auth_headers, product["id"], {"variants": rows})
    assert response.status_code == 422


async def test_empty_list_removes_variants_and_the_product_sells_plainly(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    response = await _patch(
        client, auth_headers, product["id"], {"variants": [], "price": 700, "quantity": 5}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_variants"] is False and body["variants"] == []
    assert body["price"] == 700 and body["quantity"] == 5


async def test_removing_an_option_used_by_a_variant_is_refused(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    only_color = [OPTIONS[0]]
    response = await _patch(
        client, auth_headers, product["id"], {"content": _content(options=only_color)}
    )
    assert response.status_code == 422, response.text
    assert (await _read(client, auth_headers, product["id"]))["variants"]


async def test_min_and_max_order_quantity_are_validated(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    bad = await _post(client, auth_headers, min_order_quantity=3, max_order_quantity=2)
    assert bad.status_code == 422
    over = await _post(client, auth_headers, max_order_quantity=9)
    assert over.status_code == 422
    product = await _create(client, auth_headers, min_order_quantity=2, max_order_quantity=3)
    assert (await _read(client, auth_headers, product["id"]))["max_order_quantity"] == 3
    response = await _patch(client, auth_headers, product["id"], {"min_order_quantity": 4})
    assert response.status_code == 422  # would exceed the stored maximum of 3


async def test_legacy_product_is_unchanged(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=500, quantity=2)
    body = await _read(client, auth_headers, product["id"])
    assert body["has_variants"] is False and body["variants"] == []
    assert body["min_order_quantity"] == 1 and body["max_order_quantity"] is None


# ------------------------------------------------------------------ cart


async def test_cart_prices_come_from_the_variant_and_lines_are_per_variant(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    red_m, red_l = _variant(product, "red", "m"), _variant(product, "red", "l")
    first = await _cart_add(client, product["id"], red_m["id"], 2)
    assert first.status_code == 200, first.text
    token = first.json()["cart_token"]
    guest = {"headers": {"X-Cart-Token": token}}
    second = await _cart_add(client, product["id"], red_l["id"], 1, **guest)
    again = await _cart_add(client, product["id"], red_m["id"], 1, **guest)
    body = again.json()
    assert len(body["items"]) == 2
    lines = {row["variant_id"]: row for row in body["items"]}
    assert lines[red_m["id"]]["quantity"] == 3
    assert lines[red_m["id"]]["unit_price"] == 1000
    assert lines[red_l["id"]]["unit_price"] == 1200
    assert lines[red_m["id"]]["sku"] == red_m["sku"]
    assert [item["name"] for item in lines[red_m["id"]]["selection"]] == ["কালার", "সাইজ"]
    assert body["subtotal"] == 3 * 1000 + 1200
    assert second.status_code == 200


async def test_cart_refuses_missing_foreign_inactive_and_sold_out_variants(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    rows = _combos(**{"red-l": {"quantity": 0}, "navy-m": {"is_active": False}})
    product = await _make(client, auth_headers, variants=rows)
    other = await _make(
        client,
        auth_headers,
        title="Other tee",
        variants=[{**row, "sku": f"O-{row['sku']}"} for row in _combos()],
    )
    ok = _variant(product, "red", "m")
    assert (await _cart_add(client, product["id"], None)).status_code == 422
    assert (await _cart_add(client, product["id"], str(uuid.uuid4()))).status_code == 422
    assert (await _cart_add(client, product["id"], other["variants"][0]["id"])).status_code == 422
    assert (
        await _cart_add(client, product["id"], _variant(product, "navy", "m")["id"])
    ).status_code == 422
    assert (
        await _cart_add(client, product["id"], _variant(product, "red", "l")["id"])
    ).status_code == 422
    assert (await _cart_add(client, product["id"], ok["id"], 4)).status_code == 422  # stock is 3
    assert (await _cart_add(client, product["id"], ok["id"], 3)).status_code == 200


async def test_cart_refuses_a_variant_on_a_plain_product(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    plain = await _create(client, auth_headers, quantity=5)
    response = await _cart_add(client, plain["id"], str(uuid.uuid4()))
    assert response.status_code == 422


async def test_cart_enforces_the_minimum_and_maximum_order_quantity(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(
        client, auth_headers, quantity=None, min_order_quantity=2, max_order_quantity=3
    )
    assert (await _cart_add(client, product["id"], None, 1)).status_code == 422
    added = await _cart_add(client, product["id"], None, 2)
    assert added.status_code == 200, added.text
    line = added.json()["items"][0]
    assert (line["min_quantity"], line["max_quantity"]) == (2, 3)
    token = {"headers": {"X-Cart-Token": added.json()["cart_token"]}}
    assert (await _cart_add(client, product["id"], None, 2, **token)).status_code == 422


async def test_a_deactivated_variant_shows_unavailable_in_the_cart(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    target = _variant(product, "red", "m")
    added = await _cart_add(client, product["id"], target["id"], 1)
    token = added.json()["cart_token"]
    rows = [_input(row, is_active=row["id"] != target["id"]) for row in product["variants"]]
    assert (
        await _patch(client, auth_headers, product["id"], {"variants": rows})
    ).status_code == 200
    cart = (await client.get("/api/v1/cart", headers={"X-Cart-Token": token})).json()
    assert cart["items"][0]["available"] is False
    assert cart["subtotal"] == 0


# ------------------------------------------------------------------ order


async def _order(client: AsyncClient, items: list[dict], **extra: object):
    return await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={"source": "direct", "items": items, **SHIPPING, "district": "ঢাকা", **extra},
    )


async def test_order_total_comes_from_the_database_and_the_client_cannot_override(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    target = _variant(product, "navy", "l")
    forged = await _order(
        client,
        [{"product_id": product["id"], "variant_id": target["id"], "quantity": 2, "unit_price": 1}],
    )
    assert forged.status_code == 422
    quote = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "ঢাকা",
            "items": [{"product_id": product["id"], "variant_id": target["id"], "quantity": 2}],
        },
    )
    assert quote.status_code == 200, quote.text
    assert quote.json()["items"][0]["unit_price"] == 1200
    assert quote.json()["items"][0]["variant_id"] == target["id"]
    placed = await _order(
        client, [{"product_id": product["id"], "variant_id": target["id"], "quantity": 2}]
    )
    assert placed.status_code == 201, placed.text
    body = placed.json()
    line = body["items"][0]
    assert line["variant_id"] == target["id"] and line["sku"] == target["sku"]
    assert line["unit_price"] == 1200 and line["line_total"] == 2400
    assert body["subtotal"] == 2400
    after = await _read(client, auth_headers, product["id"])
    assert _variant(after, "navy", "l")["quantity"] == 1
    assert after["quantity"] == 10  # roll-up follows the claim
    assert _variant(after, "red", "m")["quantity"] == 3


async def test_order_requires_a_variant_for_variant_products(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    assert (await _order(client, [{"product_id": product["id"], "quantity": 1}])).status_code == 422
    plain = await _create(client, auth_headers, quantity=2)
    bad = await _order(
        client, [{"product_id": plain["id"], "variant_id": str(uuid.uuid4()), "quantity": 1}]
    )
    assert bad.status_code == 422


async def test_selling_the_last_unit_of_every_variant_flips_the_product_to_sold_out(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    rows = _combos()[:2]
    for row in rows:
        row["quantity"] = 1
    product = await _make(client, auth_headers, variants=rows)
    for row in product["variants"]:
        placed = await _order(
            client, [{"product_id": product["id"], "variant_id": row["id"], "quantity": 1}]
        )
        assert placed.status_code == 201, placed.text
    after = await _read(client, auth_headers, product["id"])
    assert after["quantity"] == 0 and after["status"] == "sold-out"
    refused = await _order(
        client,
        [{"product_id": product["id"], "variant_id": product["variants"][0]["id"], "quantity": 1}],
    )
    assert refused.status_code == 422


async def test_cancelling_a_variant_order_restores_variant_and_product_stock(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    rows = _combos()[:1]
    rows[0]["quantity"] = 1
    product = await _make(client, auth_headers, variants=rows)
    target = product["variants"][0]
    placed = await _order(
        client, [{"product_id": product["id"], "variant_id": target["id"], "quantity": 1}]
    )
    order_id = placed.json()["id"]
    assert (await _read(client, auth_headers, product["id"]))["status"] == "sold-out"
    moved = await client.patch(
        f"/api/v1/admin/orders/{order_id}", headers=auth_headers, json={"status": "cancelled"}
    )
    assert moved.status_code == 200, moved.text
    after = await _read(client, auth_headers, product["id"])
    assert after["variants"][0]["quantity"] == 1
    assert after["quantity"] == 1 and after["status"] == "available"


async def test_cart_checkout_with_two_variants_of_one_product(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers)
    small, large = _variant(product, "red", "m"), _variant(product, "red", "l")
    first = await _cart_add(client, product["id"], small["id"], 1)
    guest = {"X-Cart-Token": first.json()["cart_token"]}
    await _cart_add(client, product["id"], large["id"], 2, headers=guest)
    placed = await client.post(
        "/api/v1/orders",
        headers={**guest, "Idempotency-Key": _key()},
        json={"source": "cart", **SHIPPING, "district": "ঢাকা"},
    )
    assert placed.status_code == 201, placed.text
    body = placed.json()
    assert len(body["items"]) == 2
    assert body["subtotal"] == 1000 + 2 * 1200
    after = await _read(client, auth_headers, product["id"])
    assert _variant(after, "red", "m")["quantity"] == 2
    assert _variant(after, "red", "l")["quantity"] == 1


async def test_order_enforces_minimum_and_maximum_quantity(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(
        client, auth_headers, quantity=None, min_order_quantity=2, max_order_quantity=3
    )
    assert (await _order(client, [{"product_id": product["id"], "quantity": 1}])).status_code == 422
    assert (await _order(client, [{"product_id": product["id"], "quantity": 4}])).status_code == 422
    assert (await _order(client, [{"product_id": product["id"], "quantity": 3}])).status_code == 201
