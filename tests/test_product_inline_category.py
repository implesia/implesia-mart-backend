"""The product form creates a category, then saves the product in it (no new endpoints)."""

import uuid

from httpx import AsyncClient

from tests.test_catalog_categories import ADMIN, PUBLIC, _cat, _form
from tests.test_products import _create as create_product
from tests.test_products import _product

PRODUCTS = "/api/v1/admin/products"


async def test_product_is_saved_in_a_category_created_a_moment_earlier(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    root = await _cat(client, auth_headers, "Trending")
    child = await _cat(client, auth_headers, "Gadgets", root["id"])

    # the new category is in the admin list straight away, with its parent and depth
    rows = {r["id"]: r for r in (await client.get(ADMIN, headers=auth_headers)).json()["items"]}
    assert rows[child["id"]]["parent_id"] == root["id"]
    assert rows[child["id"]]["depth"] == 2  # the top level is 1

    product = await create_product(
        client, auth_headers, title="Inline", category=None, category_id=child["id"]
    )
    assert product["category_id"] == child["id"]
    assert [p["name"] for p in product["category_path"]] == ["Trending", "Gadgets"]

    # persisted: reading it back returns the same category
    again = await client.get(f"{PRODUCTS}/{product['id']}", headers=auth_headers)
    assert again.status_code == 200
    assert again.json()["category_id"] == child["id"]
    assert [p["slug"] for p in again.json()["category_path"]] == [
        root["slug"],
        child["slug"],
    ]


async def test_duplicate_name_under_the_same_parent_is_a_clear_409(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    root = await _cat(client, auth_headers, "Trending")
    await _cat(client, auth_headers, "Gadgets", root["id"])
    dup = await client.post(
        ADMIN,
        headers=auth_headers,
        files=_form({"name": "  gadgets ", "parent_id": root["id"]}),
    )
    assert dup.status_code == 409
    error = dup.json()["error"]
    assert error["code"] == "conflict"
    assert "already exists here" in error["message"]
    # the same name at the top level is a different category
    assert (await _cat(client, auth_headers, "Gadgets"))["parent_id"] is None


async def test_product_refuses_a_category_that_does_not_exist(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        PRODUCTS,
        headers=auth_headers,
        files=_form(_product(category=None, category_id=str(uuid.uuid4()))),
    )
    assert response.status_code == 422
    assert "Category not found" in response.json()["error"]["message"]


async def test_product_in_a_hidden_category_is_saved_but_not_public(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    hidden = await _cat(client, auth_headers, "Draft shelf", is_active=False)
    product = await create_product(
        client, auth_headers, title="Quiet", category=None, category_id=hidden["id"]
    )
    assert product["category_id"] == hidden["id"]
    assert (await client.get(f"{PUBLIC}/{hidden['slug']}/products")).json()["items"] == []


async def test_a_viewer_cannot_create_a_category(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "inline-cat-viewer@implesia.com",
            "full_name": "Inline Cat Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "inline-cat-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = await client.post(ADMIN, headers=viewer, files=_form({"name": "Nope"}))
    assert denied.status_code == 403
    assert (await client.get(ADMIN, headers=auth_headers)).json()["items"] == []
