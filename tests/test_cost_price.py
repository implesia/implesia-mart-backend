"""cost_price is an admin field. Shoppers never receive it, and a viewer cannot write it."""

from httpx import AsyncClient

from app.schemas.product import AdminProductCard, PublicProductCard, PublicProductDetail
from tests.test_products import _create, _parts, _product


async def test_admin_can_set_cost_and_the_storefront_cannot_see_it(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert "cost_price" in AdminProductCard.model_fields
    assert "cost_price" not in PublicProductCard.model_fields
    assert "cost_price" not in PublicProductDetail.model_fields

    created = await _create(
        client,
        auth_headers,
        title="Costed lamp",
        slug="costed-lamp",
        price=15000,
        cost_price="12.50",
        quantity=4,
        published=True,
    )
    assert created["cost_price"] == 12.5
    assert created["price"] == 15000

    admin_get = await client.get(f"/api/v1/admin/products/{created['id']}", headers=auth_headers)
    assert admin_get.status_code == 200, admin_get.text
    assert admin_get.json()["cost_price"] == 12.5

    listed = await client.get(
        "/api/v1/admin/products", headers=auth_headers, params={"q": "Costed lamp"}
    )
    assert listed.status_code == 200, listed.text
    card = next(item for item in listed.json()["items"] if item["id"] == created["id"])
    assert card["cost_price"] == 12.5

    kept = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"title": "Costed lamp renamed"}),
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["cost_price"] == 12.5
    assert kept.json()["title"] == "Costed lamp renamed"

    cleared = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"cost_price": None}),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cost_price"] is None

    restored = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"cost_price": 40}),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["cost_price"] == 40

    for path in (
        f"/api/v1/products/{created['id']}",
        "/api/v1/products/by-slug/costed-lamp",
        "/api/v1/products",
        "/api/v1/search?q=Costed",
        "/api/v1/categories/fashion/products",
        "/api/v1/home/featured",
        "/api/v1/home/showcase",
    ):
        public = await client.get(path)
        assert public.status_code == 200, path
        assert "cost_price" not in public.text, path

    negative = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(_product(title="Negative cost", cost_price=-1)),
    )
    assert negative.status_code == 400, negative.text
    assert negative.json()["errors"][0]["field"] == "costPrice"

    rejected = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"cost_price": -5}),
    )
    assert rejected.status_code == 422, rejected.text
    still = await client.get(f"/api/v1/admin/products/{created['id']}", headers=auth_headers)
    assert still.json()["cost_price"] == 40


async def test_viewer_cannot_write_cost_price(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, title="Guarded lamp", cost_price=25, quantity=1)
    viewer_user = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "cost-viewer@implesia.com",
            "full_name": "Cost viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert viewer_user.status_code == 201, viewer_user.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "cost-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=viewer,
        files=_parts({"cost_price": 1}),
    )
    assert denied.status_code == 403
    hidden = await client.get(f"/api/v1/admin/products/{created['id']}", headers=viewer)
    assert hidden.status_code == 403
    kept = await client.get(f"/api/v1/admin/products/{created['id']}", headers=auth_headers)
    assert kept.json()["cost_price"] == 25
