from httpx import AsyncClient

from tests.test_orders import SHIPPING, _key
from tests.test_products import _create

OPTIONS = [
    {
        "id": "color-main",
        "name": "কালার",
        "kind": "color",
        "values": [
            {"id": "red", "label": "লাল", "swatch": "#B42318"},
            {"id": "navy", "label": "নেভি", "swatch": "#1D4E89"},
        ],
    },
    {
        "id": "size-main",
        "name": "সাইজ",
        "kind": "size",
        "values": [
            {"id": "m", "label": "M"},
            {"id": "l", "label": "L"},
        ],
    },
]


def _content() -> dict:
    return {
        "tagline": "হাতে তৈরি",
        "description": "কাস্টম এমব্রয়ডারি গাউন।",
        "unit_label": "শুরু",
        "highlights": ["হাতে তৈরি"],
        "options": OPTIONS,
    }


def _choice(group_id: str, value_id: str) -> dict:
    return {"group_id": group_id, "value_id": value_id}


async def test_public_detail_lists_saved_options(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, content=_content(), quantity=4)
    detail = await client.get(f"/api/v1/products/{created['id']}")
    assert detail.status_code == 200, detail.text
    options = detail.json()["options"]
    assert [item["name"] for item in options] == ["কালার", "সাইজ"]
    assert options[0]["values"][0]["swatch"] == "#b42318"
    assert options[1]["kind"] == "size"


async def test_cart_and_order_store_the_chosen_labels(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, content=_content(), quantity=4, price=500)
    missing = await client.post(
        "/api/v1/cart/items",
        headers=auth_headers,
        json={"product_id": created["id"], "quantity": 1},
    )
    assert missing.status_code == 422

    added = await client.post(
        "/api/v1/cart/items",
        json={
            "product_id": created["id"],
            "quantity": 1,
            "selection": [_choice("color-main", "red"), _choice("size-main", "m")],
        },
    )
    assert added.status_code == 200, added.text
    guest = {"X-Cart-Token": added.json()["cart_token"]}
    line = added.json()["items"][0]
    assert line["selection"] == [
        {"name": "কালার", "label": "লাল", "swatch": "#b42318"},
        {"name": "সাইজ", "label": "M", "swatch": ""},
    ]

    changed = await client.post(
        "/api/v1/cart/items",
        headers=guest,
        json={
            "product_id": created["id"],
            "quantity": 1,
            "selection": [_choice("color-main", "navy"), _choice("size-main", "l")],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["item_count"] == 2
    assert changed.json()["items"][0]["selection"][0]["label"] == "নেভি"

    placed = await client.post(
        "/api/v1/orders",
        headers={**guest, "Idempotency-Key": _key()},
        json={"source": "cart", **SHIPPING},
    )
    assert placed.status_code == 201, placed.text
    assert placed.json()["items"][0]["selection"][1]["label"] == "L"


async def test_direct_order_requires_every_option(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, content=_content(), quantity=3, price=200)
    partial = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [
                {
                    "product_id": created["id"],
                    "quantity": 1,
                    "selection": [_choice("color-main", "red")],
                }
            ],
            **SHIPPING,
        },
    )
    assert partial.status_code == 422

    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [
                {
                    "product_id": created["id"],
                    "quantity": 1,
                    "selection": [_choice("color-main", "navy"), _choice("size-main", "m")],
                }
            ],
            **SHIPPING,
        },
    )
    assert placed.status_code == 201, placed.text
    assert placed.json()["items"][0]["selection"][0] == {
        "name": "কালার",
        "label": "নেভি",
        "swatch": "#1d4e89",
    }

    plain = await _create(client, auth_headers, title="Plain lamp", slug="plain-lamp", price=100)
    extra = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [
                {
                    "product_id": plain["id"],
                    "quantity": 1,
                    "selection": [_choice("color-main", "red")],
                }
            ],
            **SHIPPING,
        },
    )
    assert extra.status_code == 422
