import json

from httpx import AsyncClient


def _product(**overrides: object) -> dict:
    body: dict = {
        "title": "Featured gown",
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


async def test_public_featured_seeds_published_featured_products(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    flagged = await _create(
        client, auth_headers, title="Flagged lamp", slug="flagged-lamp", featured=True
    )
    await _create(client, auth_headers, title="Plain scarf", slug="plain-scarf", featured=False)
    await _create(
        client,
        auth_headers,
        title="Hidden gown",
        slug="hidden-gown",
        featured=True,
        published=False,
    )

    response = await client.get("/api/v1/home/featured")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == "ফিচার্ড প্রোডাক্ট"
    assert body["view_all_label"] == "সব দেখুন"
    assert body["view_all_href"] == "/products?view=featured"
    assert body["product_ids"] == [flagged["id"]]


async def test_featured_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/featured")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "featured-viewer@implesia.com",
            "full_name": "Featured Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "featured-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/home/featured/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"product_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert denied.status_code == 403


async def test_editor_can_feature_reorder_hide_and_remove_a_product(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.services.home import featured_service

    flagged = await _create(
        client, auth_headers, title="Flagged lamp", slug="flagged-lamp", featured=True
    )
    extra = await _create(client, auth_headers, title="Plain scarf", slug="plain-scarf")
    hidden = await _create(
        client,
        auth_headers,
        title="Hidden gown",
        slug="hidden-gown",
        published=False,
    )

    listed = await client.get("/api/v1/admin/home/featured", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [item["product_id"] for item in body["items"]] == [flagged["id"]]
    assert {choice["id"] for choice in body["choices"]} >= {
        flagged["id"],
        extra["id"],
        hidden["id"],
    }

    created = await client.post(
        "/api/v1/admin/home/featured/items",
        headers=auth_headers,
        json={"product_id": extra["id"]},
    )
    assert created.status_code == 201, created.text
    pick = created.json()
    assert pick["product_id"] == extra["id"]
    assert pick["product"]["title"] == "Plain scarf"

    duplicate = await client.post(
        "/api/v1/admin/home/featured/items",
        headers=auth_headers,
        json={"product_id": extra["id"]},
    )
    assert duplicate.status_code == 422

    monkeypatch.setattr(featured_service, "MAX_ITEMS", 2)
    capped = await client.post(
        "/api/v1/admin/home/featured/items",
        headers=auth_headers,
        json={"product_id": hidden["id"]},
    )
    assert capped.status_code == 422
    monkeypatch.setattr(featured_service, "MAX_ITEMS", 12)

    concealed = await client.post(
        "/api/v1/admin/home/featured/items",
        headers=auth_headers,
        json={"product_id": hidden["id"]},
    )
    assert concealed.status_code == 201, concealed.text
    public = await client.get("/api/v1/home/featured")
    assert public.json()["product_ids"] == [flagged["id"], extra["id"]]

    again = await client.get("/api/v1/admin/home/featured", headers=auth_headers)
    ids = [item["id"] for item in again.json()["items"]]
    moved = await client.put(
        "/api/v1/admin/home/featured/items/order",
        headers=auth_headers,
        json={"ids": [pick["id"], *([item for item in ids if item != pick["id"]])]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["items"][0]["id"] == pick["id"]

    incomplete = await client.put(
        "/api/v1/admin/home/featured/items/order",
        headers=auth_headers,
        json={"ids": [pick["id"]]},
    )
    assert incomplete.status_code == 422

    heading = await client.patch(
        "/api/v1/admin/home/featured",
        headers=auth_headers,
        json={"heading": "শপ", "view_all_label": "সব", "view_all_href": ""},
    )
    assert heading.status_code == 200, heading.text
    assert heading.json()["heading"] == "শপ"
    assert heading.json()["view_all_href"] == "/products?view=featured"

    bad_link = await client.patch(
        "/api/v1/admin/home/featured",
        headers=auth_headers,
        json={"heading": "শপ", "view_all_label": "সব", "view_all_href": "nope"},
    )
    assert bad_link.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/home/featured/items/{pick['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Featured product removed"
    hidden_removed = await client.delete(
        f"/api/v1/admin/home/featured/items/{concealed.json()['id']}",
        headers=auth_headers,
    )
    assert hidden_removed.status_code == 200

    restored = await client.patch(
        "/api/v1/admin/home/featured",
        headers=auth_headers,
        json={
            "heading": "ফিচার্ড প্রোডাক্ট",
            "view_all_label": "সব দেখুন",
            "view_all_href": "/products?view=featured",
        },
    )
    assert restored.status_code == 200
    final = await client.get("/api/v1/home/featured")
    assert final.json()["product_ids"] == [flagged["id"]]
    assert final.json()["heading"] == "ফিচার্ড প্রোডাক্ট"
