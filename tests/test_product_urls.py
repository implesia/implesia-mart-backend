"""Phase 3: product pages are addressed by the stable id; the slug stays a legacy lookup."""

from httpx import AsyncClient

from tests.test_orders import SHIPPING, _key
from tests.test_products import _create, _parts, _product

INTERNAL = {
    "quantity",
    "published",
    "content",
    "sort_order",
    "created_at",
    "updated_at",
    "has_stock",
}


async def test_id_and_legacy_slug_return_the_same_product(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, title="Url Lamp", slug="url-lamp")
    by_id = await client.get(f"/api/v1/products/{created['id']}")
    by_slug = await client.get("/api/v1/products/by-slug/url-lamp")
    upper = await client.get(f"/api/v1/products/{created['id'].upper()}")
    assert by_id.status_code == by_slug.status_code == upper.status_code == 200
    assert by_id.json() == by_slug.json() == upper.json()
    assert by_id.json()["id"] == created["id"]
    assert by_id.json()["slug"] == "url-lamp"
    assert INTERNAL.isdisjoint(by_id.json())


async def test_slug_does_not_change_when_the_product_is_edited(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, title="Rename Lamp", slug="rename-lamp")
    patched = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"title": "Renamed Lamp"}),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["slug"] == "rename-lamp"
    by_id = await client.get(f"/api/v1/products/{created['id']}")
    assert by_id.json()["slug"] == "rename-lamp"
    assert by_id.json()["title"] == "Renamed Lamp"


async def test_malformed_and_deleted_ids_do_not_resolve(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    bad = await client.get("/api/v1/products/not-a-uuid")
    assert bad.status_code == 422
    assert "error" in bad.json()

    created = await _create(client, auth_headers, title="Gone Lamp", slug="gone-lamp")
    deleted = await client.delete(f"/api/v1/admin/products/{created['id']}", headers=auth_headers)
    assert deleted.status_code in (200, 204)
    for path in (f"/api/v1/products/{created['id']}", "/api/v1/products/by-slug/gone-lamp"):
        gone = await client.get(path)
        assert gone.status_code == 404
        assert gone.json()["error"]["code"] == "not_found"


async def test_unpublished_product_is_404_by_id_and_slug_alike(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(
        client, auth_headers, title="Draft Lamp", slug="draft-lamp", published=False
    )
    by_id = await client.get(f"/api/v1/products/{created['id']}")
    by_slug = await client.get("/api/v1/products/by-slug/draft-lamp")
    assert by_id.status_code == by_slug.status_code == 404
    assert by_id.json() == by_slug.json()


async def test_public_order_items_link_back_by_product_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Track Lamp", slug="track-lamp", quantity=3)
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
    lookup = {"number": placed.json()["number"], "phone": SHIPPING["phone"]}
    found = await client.post("/api/v1/orders/lookup", json=lookup)
    assert found.status_code == 200, found.text
    assert found.json()["items"][0]["product_id"] == product["id"]


def test_product_helper_defaults_are_published() -> None:
    assert _product()["published"] is True
