"""POST /admin/products answers problems as {"errors": [{field, message, fix}]} in Bengali."""

import pytest
from httpx import AsyncClient

from app.services import product_service
from tests.test_products import _parts, _product

PRODUCTS = "/api/v1/admin/products"


def _only_keys(body: dict) -> None:
    assert set(body) == {"errors"}
    for item in body["errors"]:
        assert set(item) == {"field", "message", "fix"}
        assert item["message"] and item["fix"]


async def test_missing_price_uses_the_exact_contract(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = _product()
    body.pop("price")
    response = await client.post(PRODUCTS, headers=auth_headers, files=_parts(body))
    assert response.status_code == 400
    assert response.json() == {
        "errors": [
            {
                "field": "price",
                "message": "দাম দিতে হবে",
                "fix": "০ বা তার বেশি একটা পূর্ণ সংখ্যা লিখুন (টাকায়)",
            }
        ]
    }


async def test_every_invalid_field_is_reported_with_form_keys(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = _product(
        title="   ",
        price=-5,
        quantity="many",
        category=None,
        compare_at_price=10_000_001,
        max_order_quantity=1001,
        status="gone",
        badge_ids=["not-a-uuid"],
    )
    response = await client.post(PRODUCTS, headers=auth_headers, files=_parts(body))
    assert response.status_code == 400
    data = response.json()
    _only_keys(data)
    fields = [item["field"] for item in data["errors"]]
    assert set(fields) >= {
        "title",
        "price",
        "quantity",
        "compareAtPrice",
        "orderLimits",
        "category",
        "status",
        "badges",
    }
    price = next(item for item in data["errors"] if item["field"] == "price")
    assert price["message"] == "দাম ০-এর কম হতে পারে না"
    big = next(item for item in data["errors"] if item["field"] == "compareAtPrice")
    assert "১০,০০০,০০০" in big["fix"]
    # Bengali only: no English validator text leaks through.
    assert "Input should" not in response.text and "Value error" not in response.text


async def test_missing_or_broken_payload_is_a_400(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    missing = await client.post(PRODUCTS, headers=auth_headers, data={"image_alts": "[]"})
    assert missing.status_code == 400
    assert missing.json()["errors"][0]["field"] == "form"
    broken = await client.post(PRODUCTS, headers=auth_headers, data={"payload": "{not json"})
    assert broken.status_code == 400
    _only_keys(broken.json())
    alts = await client.post(
        PRODUCTS,
        headers=auth_headers,
        files=[*_parts(_product()), ("image_alts", (None, "nope"))],
    )
    assert alts.status_code == 400
    assert alts.json()["errors"][0]["field"] == "images"


async def test_duplicate_slug_is_a_409_in_the_same_shape(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await client.post(
        PRODUCTS, headers=auth_headers, files=_parts(_product(slug="eid-gown"))
    )
    assert first.status_code == 201, first.text
    again = await client.post(
        PRODUCTS, headers=auth_headers, files=_parts(_product(slug="eid-gown", title="Other"))
    )
    assert again.status_code == 409
    _only_keys(again.json())
    assert again.json()["errors"][0]["field"] == "slug"


async def test_unexpected_errors_are_a_generic_500(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_: object, **__: object) -> None:
        raise RuntimeError("password=hunter2 at db.internal:5432")

    monkeypatch.setattr(product_service, "create_product", boom)
    response = await client.post(PRODUCTS, headers=auth_headers, files=_parts(_product()))
    assert response.status_code == 500
    _only_keys(response.json())
    assert response.json()["errors"][0]["field"] == "form"
    for leak in ("hunter2", "db.internal", "RuntimeError", "Traceback", "boom"):
        assert leak not in response.text


async def test_auth_and_other_endpoints_keep_their_formats(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.post(PRODUCTS, files=_parts(_product()))
    assert anonymous.status_code == 401
    assert "error" in anonymous.json()
    created = await client.post(PRODUCTS, headers=auth_headers, files=_parts(_product()))
    assert created.status_code == 201, created.text
    update = await client.patch(
        f"{PRODUCTS}/{created.json()['id']}",
        headers=auth_headers,
        data={"payload": '{"price": -1}'},
    )
    assert update.status_code == 422
    assert update.json()["error"]["code"] == "validation_error"
