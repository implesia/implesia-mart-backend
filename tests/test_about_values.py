from httpx import AsyncClient

SEEDED = ["কোয়ালিটি চেকড", "ক্যাশ অন ডেলিভারি", "সারাদেশে ডেলিভারি", "সহজ রিটার্ন"]


async def test_public_about_values_seed_the_principles(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/about/values")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kicker"] == "আমাদের মূলনীতি"
    assert body["title"] == "যেভাবে আমরা কাজ করি"
    assert [item["title"] for item in body["items"]] == SEEDED
    assert body["items"][0]["icon"] == "verified"
    assert "is_active" not in body["items"][0]


async def test_about_values_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/about/values")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "about-values-viewer@implesia.com",
            "full_name": "About Values Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "about-values-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/about/values/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"title": "Nope", "description": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_value(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.services import about_values_service

    monkeypatch.setattr(about_values_service, "MAX_VALUES", 4)
    blocked = await client.post(
        "/api/v1/admin/pages/about/values/items",
        headers=auth_headers,
        json={"title": "Extra", "description": "Extra"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 12 values"
    monkeypatch.setattr(about_values_service, "MAX_VALUES", 12)

    blank = await client.post(
        "/api/v1/admin/pages/about/values/items",
        headers=auth_headers,
        json={"title": "   ", "description": "Kept"},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    created = await client.post(
        "/api/v1/admin/pages/about/values/items",
        headers=auth_headers,
        json={
            "icon": "  ",
            "title": "  Value check  ",
            "description": "  Hidden principle  ",
            "is_active": False,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["title"] == "Value check"
    assert item["icon"] == "verified"
    assert item["is_active"] is False

    public = await client.get("/api/v1/pages/about/values")
    assert [entry["title"] for entry in public.json()["items"]] == SEEDED

    listed = await client.get("/api/v1/admin/pages/about/values", headers=auth_headers)
    ids = [entry["id"] for entry in listed.json()["items"]]
    moved = await client.put(
        "/api/v1/admin/pages/about/values/items/order",
        headers=auth_headers,
        json={"ids": [item["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["items"][0]["id"] == item["id"]

    incomplete = await client.put(
        "/api/v1/admin/pages/about/values/items/order",
        headers=auth_headers,
        json={"ids": [item["id"]]},
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["message"] == "Send every value in the new order"

    missing = await client.delete(
        "/api/v1/admin/pages/about/values/items/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Value not found"

    removed = await client.delete(
        f"/api/v1/admin/pages/about/values/items/{item['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Value removed"

    public = await client.get("/api/v1/pages/about/values")
    assert [entry["title"] for entry in public.json()["items"]] == SEEDED
