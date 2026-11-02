"""Drafts: `published: false` needs only a name and stays admin-only until it is published."""

from httpx import AsyncClient

from tests.test_products import _parts, _product

ADMIN = "/api/v1/admin/products"


async def _draft(client: AsyncClient, headers: dict[str, str], **body: object) -> dict:
    response = await client.post(ADMIN, headers=headers, files=_parts({"published": False, **body}))
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_draft_needs_only_a_name(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _draft(client, auth_headers, title="Half Done Lamp")
    assert created["published"] is False
    assert created["category_id"] is None
    assert created["price"] == 0
    assert created["image_src"] == ""

    nameless = await client.post(
        ADMIN, headers=auth_headers, files=_parts({"published": False, "title": "  "})
    )
    assert nameless.status_code == 400
    assert [item["field"] for item in nameless.json()["errors"]] == ["title"]


async def test_publishing_still_requires_price_category_and_image(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        ADMIN, headers=auth_headers, files=_parts({"published": True, "title": "Lamp"})
    )
    assert response.status_code == 400
    fields = {item["field"] for item in response.json()["errors"]}
    assert fields == {"price", "category"}

    no_image = await client.post(ADMIN, headers=auth_headers, files=_parts(_product(image_src="")))
    assert no_image.status_code == 400
    assert no_image.json()["errors"][0]["field"] == "images"


async def test_drafts_stay_off_the_storefront(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    draft = await _draft(client, auth_headers, title="Secret Draft Lamp")
    assert (await client.get(f"/api/v1/products/{draft['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/products/by-slug/{draft['slug']}")).status_code == 404
    catalog = (await client.get("/api/v1/products")).json()
    assert all(item["id"] != draft["id"] for item in catalog["items"])
    search = await client.get("/api/v1/search", params={"q": "Secret Draft Lamp"})
    assert draft["id"] not in search.text


async def test_admin_list_filters_by_status(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    draft = await _draft(client, auth_headers, title="Draft Only Lamp")
    live = await client.post(ADMIN, headers=auth_headers, files=_parts(_product()))
    assert live.status_code == 201
    drafts = (await client.get(ADMIN, headers=auth_headers, params={"visibility": "hidden"})).json()
    published = (
        await client.get(ADMIN, headers=auth_headers, params={"visibility": "live"})
    ).json()
    assert [item["id"] for item in drafts["items"]] == [draft["id"]]
    assert [item["id"] for item in published["items"]] == [live.json()["id"]]
    assert drafts["metrics"]["hidden"] == 1 and drafts["metrics"]["live"] == 1


async def test_draft_publishes_only_when_complete_and_can_go_back(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    draft = await _draft(client, auth_headers, title="Lamp In Progress")
    url = f"{ADMIN}/{draft['id']}"

    early = await client.patch(url, headers=auth_headers, data={"payload": '{"published": true}'})
    assert early.status_code == 422
    assert (await client.get(url, headers=auth_headers)).json()["published"] is False

    completed = await client.patch(
        url,
        headers=auth_headers,
        files=_parts(
            {
                "published": True,
                "category": "fashion",
                "price": 1200,
                "image_src": "/images/products/lamp.jpg",
            }
        ),
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["published"] is True
    assert (await client.get(f"/api/v1/products/{draft['id']}")).status_code == 200

    back = await client.patch(url, headers=auth_headers, data={"payload": '{"published": false}'})
    assert back.status_code == 200
    assert back.json()["published"] is False
    assert (await client.get(f"/api/v1/products/{draft['id']}")).status_code == 404
