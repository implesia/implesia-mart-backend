"""Product SEO fields and editable slugs (old slugs keep resolving)."""

from httpx import AsyncClient

from tests.test_products import _create, _parts


async def _patch(client: AsyncClient, headers: dict[str, str], product_id: str, body: dict):
    return await client.patch(
        f"/api/v1/admin/products/{product_id}", headers=headers, files=_parts(body)
    )


async def test_seo_fields_are_saved_and_public(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(
        client,
        auth_headers,
        title="Seo Lamp",
        slug="seo-lamp",
        seo_title="  Seo   Lamp — warm light ",
        seo_description="A warm desk lamp.",
        seo_keywords="lamp, desk lamp,  Lamp , ,light",
    )
    assert created["seo_title"] == "Seo Lamp — warm light"
    assert created["seo_keywords"] == "lamp, desk lamp, light"

    public = (await client.get("/api/v1/products/by-slug/seo-lamp")).json()
    assert public["seo_title"] == "Seo Lamp — warm light"
    assert public["seo_description"] == "A warm desk lamp."
    assert public["seo_keywords"] == "lamp, desk lamp, light"

    patched = await _patch(client, auth_headers, created["id"], {"seo_title": ""})
    assert patched.status_code == 200, patched.text
    assert patched.json()["seo_title"] == ""
    assert patched.json()["seo_description"] == "A warm desk lamp."


async def test_seo_fields_are_length_checked(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, title="Long Lamp", slug="long-lamp")
    for field, size in (("seo_title", 121), ("seo_description", 321), ("seo_keywords", 501)):
        bad = await _patch(client, auth_headers, created["id"], {field: "x" * size})
        assert bad.status_code == 422, (field, bad.text)


async def test_slug_edit_keeps_the_old_slug_working(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, title="Move Lamp", slug="move-lamp")
    moved = await _patch(client, auth_headers, created["id"], {"slug": "  Moved-Lamp "})
    assert moved.status_code == 200, moved.text
    assert moved.json()["slug"] == "moved-lamp"

    for slug in ("moved-lamp", "move-lamp"):
        found = await client.get(f"/api/v1/products/by-slug/{slug}")
        assert found.status_code == 200, slug
        assert found.json()["id"] == created["id"]
        assert found.json()["slug"] == "moved-lamp"

    # Moving again keeps both earlier slugs; moving back drops the redirect.
    assert (await _patch(client, auth_headers, created["id"], {"slug": "third-lamp"})).is_success
    for slug in ("move-lamp", "moved-lamp"):
        assert (await client.get(f"/api/v1/products/by-slug/{slug}")).json()["slug"] == "third-lamp"
    back = await _patch(client, auth_headers, created["id"], {"slug": "move-lamp"})
    assert back.json()["slug"] == "move-lamp"
    assert (await client.get("/api/v1/products/by-slug/third-lamp")).json()["slug"] == "move-lamp"


async def test_slug_edit_is_validated_and_unique(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await _create(client, auth_headers, title="Taken Lamp", slug="taken-lamp")
    second = await _create(client, auth_headers, title="Other Lamp", slug="other-lamp")

    taken = await _patch(client, auth_headers, second["id"], {"slug": "taken-lamp"})
    assert taken.status_code == 409
    assert [item["field"] for item in taken.json()["errors"]] == ["slug"]
    for bad in ("Bad Slug", "trailing-", "ü-lamp", "x" * 161):
        assert (await _patch(client, auth_headers, second["id"], {"slug": bad})).status_code == 422

    # Same slug = no change, no redirect.
    same = await _patch(client, auth_headers, first["id"], {"slug": "taken-lamp"})
    assert same.status_code == 200
    assert same.json()["slug"] == "taken-lamp"


async def test_a_new_product_can_take_an_old_slug(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    old = await _create(client, auth_headers, title="Old Lamp", slug="old-lamp")
    assert (await _patch(client, auth_headers, old["id"], {"slug": "older-lamp"})).is_success
    fresh = await _create(client, auth_headers, title="Fresh Lamp", slug="old-lamp")
    found = (await client.get("/api/v1/products/by-slug/old-lamp")).json()
    assert found["id"] == fresh["id"]
    assert (await client.get("/api/v1/products/by-slug/older-lamp")).json()["id"] == old["id"]


async def test_old_slug_of_a_hidden_product_is_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, title="Hide Lamp", slug="hide-lamp")
    assert (await _patch(client, auth_headers, created["id"], {"slug": "hidden-lamp"})).is_success
    assert (await _patch(client, auth_headers, created["id"], {"published": False})).is_success
    assert (await client.get("/api/v1/products/by-slug/hide-lamp")).status_code == 404
