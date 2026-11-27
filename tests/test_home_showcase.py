import json

from httpx import AsyncClient


def _product(**overrides: object) -> dict:
    body: dict = {
        "title": "Showcase gown",
        "subtitle": "Hand embroidered",
        "category": "fashion",
        "price": 15000,
        "compare_at_price": None,
        "quantity": None,
        "status": "available",
        "badge": "New",
        "image_src": "/images/products/gown.jpg",
        "featured": False,
        "published": True,
        "content": {
            "tagline": "হাতে তৈরি",
            "description": "কাস্টম গাউন।",
            "unit_label": "শুরু",
            "image_alt": "গাউন",
            "highlights": ["হাতে তৈরি"],
            "specs": [{"label": "কাপড়", "value": "কটন", "group": "fabric"}],
            "faqs": [{"question": "কত দিন?", "answer": "৩ দিন।"}],
        },
    }
    body.update(overrides)
    return body


async def _create(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    response = await client.post(
        "/api/v1/admin/products",
        headers=headers,
        files=[("payload", (None, json.dumps(_product(**overrides))))],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _row(body: dict, key: str) -> dict:
    return next(row for row in body["rows"] if row["key"] == key)


async def test_public_showcase_seeds_each_category(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    lamp = await _create(
        client, auth_headers, title="Lamp", slug="showcase-lamp", category="gadgets"
    )
    await _create(
        client,
        auth_headers,
        title="Hidden holder",
        slug="hidden-holder",
        category="gadgets",
        published=False,
    )
    gown = await _create(
        client, auth_headers, title="Gown", slug="showcase-gown", category="fashion"
    )

    response = await client.get("/api/v1/home/showcase")
    assert response.status_code == 200, response.text
    body = response.json()
    gadgets = _row(body, "gadgets")
    fashion = _row(body, "fashion")
    assert gadgets["heading"] == "ট্রেন্ডিং গ্যাজেট"
    assert gadgets["href"] == "/products?category=gadgets"
    assert gadgets["product_ids"] == [lamp["id"]]
    assert fashion["heading"] == "গর্জিয়াস ড্রেস"
    assert fashion["product_ids"] == [gown["id"]]


async def test_public_showcase_drops_a_pinned_product_once_hidden(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    lamp = await _create(
        client, auth_headers, title="Lamp", slug="showcase-lamp", category="gadgets"
    )
    assert _row((await client.get("/api/v1/home/showcase")).json(), "gadgets")["product_ids"] == [
        lamp["id"]
    ]

    hidden = await client.patch(
        f"/api/v1/admin/products/{lamp['id']}",
        headers=auth_headers,
        files=[("payload", (None, json.dumps({"published": False})))],
    )
    assert hidden.status_code == 200, hidden.text

    public = await client.get("/api/v1/home/showcase")
    assert _row(public.json(), "gadgets")["product_ids"] == []
    admin = await client.get("/api/v1/admin/home/showcase", headers=auth_headers)
    pinned = _row(admin.json(), "gadgets")["items"]
    assert [item["product"]["published"] for item in pinned] == [False]


async def test_showcase_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/showcase")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "showcase-viewer@implesia.com",
            "full_name": "Showcase Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "showcase-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/home/showcase/rows/gadgets/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"product_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert denied.status_code == 403


async def test_editor_can_add_reorder_and_remove_a_showcase_product(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    lamp = await _create(
        client, auth_headers, title="Lamp", slug="showcase-lamp", category="gadgets"
    )
    scarf = await _create(
        client, auth_headers, title="Scarf", slug="showcase-scarf", category="gadgets"
    )
    await _create(
        client, auth_headers, title="Gown", slug="showcase-gown", category="fashion"
    )

    listed = await client.get("/api/v1/admin/home/showcase", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    gadgets = _row(listed.json(), "gadgets")
    assert {item["product_id"] for item in gadgets["items"]} == {lamp["id"], scarf["id"]}

    hidden = await _create(
        client,
        auth_headers,
        title="Hidden lamp",
        slug="showcase-hidden-lamp",
        category="gadgets",
        published=False,
    )
    wrong = await client.post(
        "/api/v1/admin/home/showcase/rows/gadgets/items",
        headers=auth_headers,
        json={"product_id": hidden["id"]},
    )
    assert wrong.status_code == 422

    duplicate = await client.post(
        "/api/v1/admin/home/showcase/rows/gadgets/items",
        headers=auth_headers,
        json={"product_id": lamp["id"]},
    )
    assert duplicate.status_code == 422

    extra = await _create(
        client, auth_headers, title="Cable", slug="showcase-cable", category="gadgets"
    )
    created = await client.post(
        "/api/v1/admin/home/showcase/rows/gadgets/items",
        headers=auth_headers,
        json={"product_id": extra["id"]},
    )
    assert created.status_code == 201, created.text
    pick = created.json()
    assert pick["product"]["title"] == "Cable"

    again = await client.get("/api/v1/admin/home/showcase", headers=auth_headers)
    ids = [item["id"] for item in _row(again.json(), "gadgets")["items"]]
    moved = await client.put(
        "/api/v1/admin/home/showcase/rows/gadgets/items/order",
        headers=auth_headers,
        json={"ids": [pick["id"], *[item for item in ids if item != pick["id"]]]},
    )
    assert moved.status_code == 200, moved.text
    assert _row(moved.json(), "gadgets")["items"][0]["id"] == pick["id"]

    incomplete = await client.put(
        "/api/v1/admin/home/showcase/rows/gadgets/items/order",
        headers=auth_headers,
        json={"ids": [pick["id"]]},
    )
    assert incomplete.status_code == 422

    heading = await client.patch(
        "/api/v1/admin/home/showcase/rows/gadgets",
        headers=auth_headers,
        json={"heading": "গ্যাজেট", "href": ""},
    )
    assert heading.status_code == 200, heading.text
    saved = _row(heading.json(), "gadgets")
    assert saved["heading"] == "গ্যাজেট"
    assert saved["href"] == "/products?category=gadgets"

    bad_link = await client.patch(
        "/api/v1/admin/home/showcase/rows/gadgets",
        headers=auth_headers,
        json={"heading": "গ্যাজেট", "href": "nope"},
    )
    assert bad_link.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/home/showcase/rows/gadgets/items/{pick['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Showcase product removed"

    restored = await client.patch(
        "/api/v1/admin/home/showcase/rows/gadgets",
        headers=auth_headers,
        json={"heading": "ট্রেন্ডিং গ্যাজেট", "href": "/products?category=gadgets"},
    )
    assert restored.status_code == 200
    public = await client.get("/api/v1/home/showcase")
    assert set(_row(public.json(), "gadgets")["product_ids"]) == {lamp["id"], scarf["id"]}
    assert _row(public.json(), "gadgets")["heading"] == "ট্রেন্ডিং গ্যাজেট"


async def test_showcase_choices_are_published_products_from_any_category(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Rows are not tied to their key's category: on the live catalog the `gadgets`
    category does not exist, which left the Trending row with no choices."""
    gown = await _create(
        client, auth_headers, title="Gown", slug="showcase-gown", category="fashion"
    )
    lamp = await _create(
        client, auth_headers, title="Lamp", slug="showcase-lamp", category="gadgets"
    )
    hidden = await _create(
        client,
        auth_headers,
        title="Hidden gown",
        slug="showcase-hidden-gown",
        category="fashion",
        published=False,
    )

    listed = await client.get("/api/v1/admin/home/showcase", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    for key in ("gadgets", "fashion"):
        ids = {choice["id"] for choice in _row(listed.json(), key)["choices"]}
        assert {gown["id"], lamp["id"]} <= ids
        assert hidden["id"] not in ids
        assert all(choice["published"] for choice in _row(listed.json(), key)["choices"])

    gadgets_items = _row(listed.json(), "gadgets")["items"]
    added = await client.post(
        "/api/v1/admin/home/showcase/rows/gadgets/items",
        headers=auth_headers,
        json={"product_id": gown["id"]},
    )
    assert added.status_code == 201, added.text

    # A pinned product that was hidden later can still be saved in its own slot.
    pinned = gadgets_items[0]
    await client.patch(
        f"/api/v1/admin/products/{pinned['product_id']}",
        headers=auth_headers,
        files=[("payload", (None, json.dumps({"published": False})))],
    )
    kept = await client.patch(
        f"/api/v1/admin/home/showcase/rows/gadgets/items/{pinned['id']}",
        headers=auth_headers,
        json={"product_id": pinned["product_id"]},
    )
    assert kept.status_code == 200, kept.text
    swapped = await client.patch(
        f"/api/v1/admin/home/showcase/rows/gadgets/items/{pinned['id']}",
        headers=auth_headers,
        json={"product_id": hidden["id"]},
    )
    assert swapped.status_code == 422


async def test_showcase_row_allows_more_than_twelve_products_and_reordering(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Seed the showcase first so all 15 products can be added explicitly.
    initial = await client.get("/api/v1/admin/home/showcase", headers=auth_headers)
    assert initial.status_code == 200, initial.text

    item_ids: list[str] = []
    for index in range(1, 16):
        prod = await _create(
            client,
            auth_headers,
            title=f"Showcase Item {index}",
            slug=f"showcase-item-{index}",
            category="gadgets",
        )
        added = await client.post(
            "/api/v1/admin/home/showcase/rows/gadgets/items",
            headers=auth_headers,
            json={"product_id": prod["id"]},
        )
        assert added.status_code == 201, added.text
        item_ids.append(added.json()["id"])

    listed = await client.get("/api/v1/admin/home/showcase", headers=auth_headers)
    assert len(_row(listed.json(), "gadgets")["items"]) == 15

    reversed_ids = list(reversed(item_ids))
    reordered = await client.put(
        "/api/v1/admin/home/showcase/rows/gadgets/items/order",
        headers=auth_headers,
        json={"ids": reversed_ids},
    )
    assert reordered.status_code == 200, reordered.text
    assert [item["id"] for item in _row(reordered.json(), "gadgets")["items"]] == reversed_ids


async def test_editor_can_create_reorder_and_delete_dynamic_showcase_sections(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    prod = await _create(
        client, auth_headers, title="Combo Box", slug="combo-box", category="gadgets"
    )

    # Create a new dynamic section (ASCII heading -> clean slug key)
    created = await client.post(
        "/api/v1/admin/home/showcase/rows",
        headers=auth_headers,
        json={"heading": "Winter Combos", "href": "/products?view=new"},
    )
    assert created.status_code == 201, created.text
    rows = created.json()["rows"]
    winter = next(r for r in rows if r["heading"] == "Winter Combos")
    assert winter["key"] == "winter-combos"
    assert winter["href"] == "/products?view=new"

    # Create a second dynamic section with Bangla heading -> auto-generated safe key
    bn_created = await client.post(
        "/api/v1/admin/home/showcase/rows",
        headers=auth_headers,
        json={"heading": "ঈদ স্পেশাল", "href": ""},
    )
    assert bn_created.status_code == 201, bn_created.text
    eid = next(r for r in bn_created.json()["rows"] if r["heading"] == "ঈদ স্পেশাল")
    assert eid["key"].startswith("section-")
    assert eid["href"] == "/products"

    # Pin a product into the dynamic section and confirm public API returns it
    pin = await client.post(
        f"/api/v1/admin/home/showcase/rows/{winter['key']}/items",
        headers=auth_headers,
        json={"product_id": prod["id"]},
    )
    assert pin.status_code == 201, pin.text

    # Reorder sections so Winter Combos comes before fashion
    new_keys = ["gadgets", winter["key"], "fashion", eid["key"]]
    reordered = await client.put(
        "/api/v1/admin/home/showcase/rows/order",
        headers=auth_headers,
        json={"keys": new_keys},
    )
    assert reordered.status_code == 200, reordered.text
    assert [r["key"] for r in reordered.json()["rows"]] == new_keys

    public = await client.get("/api/v1/home/showcase")
    assert public.status_code == 200
    assert [r["key"] for r in public.json()["rows"]] == new_keys
    assert _row(public.json(), winter["key"])["product_ids"] == [prod["id"]]

    # Deleting the built-in Trending (gadgets) row is rejected
    blocked = await client.delete(
        "/api/v1/admin/home/showcase/rows/gadgets",
        headers=auth_headers,
    )
    assert blocked.status_code == 422

    # Deleting a dynamic section removes it cleanly
    deleted = await client.delete(
        f"/api/v1/admin/home/showcase/rows/{winter['key']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert winter["key"] not in [r["key"] for r in deleted.json()["rows"]]
