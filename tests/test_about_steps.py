from httpx import AsyncClient

SEEDED = ["প্রোডাক্ট বাছাই করুন", "অর্ডার কনফার্ম করুন", "সারাদেশে ডেলিভারি", "হাতে পেয়ে পেমেন্ট"]


async def test_public_about_steps_seed_the_process(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/about/steps")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kicker"] == "সহজ প্রক্রিয়া"
    assert body["title"] == "কীভাবে অর্ডার করবেন"
    assert [item["title"] for item in body["items"]] == SEEDED
    assert body["items"][0]["step"] == "০১"
    assert body["items"][0]["icon"] == "search"
    assert "is_active" not in body["items"][0]


async def test_about_steps_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/about/steps")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "about-steps-viewer@implesia.com",
            "full_name": "About Steps Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "about-steps-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/about/steps/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"step": "০৫", "title": "Nope", "description": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_step(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.services import about_steps_service

    monkeypatch.setattr(about_steps_service, "MAX_STEPS", 4)
    blocked = await client.post(
        "/api/v1/admin/pages/about/steps/items",
        headers=auth_headers,
        json={"step": "০৫", "title": "Extra", "description": "Extra"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 12 steps"
    monkeypatch.setattr(about_steps_service, "MAX_STEPS", 12)

    blank = await client.post(
        "/api/v1/admin/pages/about/steps/items",
        headers=auth_headers,
        json={"step": "   ", "title": "Kept", "description": "Kept"},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Number is required."

    created = await client.post(
        "/api/v1/admin/pages/about/steps/items",
        headers=auth_headers,
        json={
            "step": "  ০৫  ",
            "icon": "  ",
            "title": "  Step check  ",
            "description": "  Hidden step  ",
            "is_active": False,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["step"] == "০৫"
    assert item["title"] == "Step check"
    assert item["icon"] == "task_alt"
    assert item["is_active"] is False

    public = await client.get("/api/v1/pages/about/steps")
    assert [entry["title"] for entry in public.json()["items"]] == SEEDED

    listed = await client.get("/api/v1/admin/pages/about/steps", headers=auth_headers)
    ids = [entry["id"] for entry in listed.json()["items"]]
    moved = await client.put(
        "/api/v1/admin/pages/about/steps/items/order",
        headers=auth_headers,
        json={"ids": [item["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["items"][0]["id"] == item["id"]

    incomplete = await client.put(
        "/api/v1/admin/pages/about/steps/items/order",
        headers=auth_headers,
        json={"ids": [item["id"]]},
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["message"] == "Send every step in the new order"

    missing = await client.delete(
        "/api/v1/admin/pages/about/steps/items/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Step not found"

    removed = await client.delete(
        f"/api/v1/admin/pages/about/steps/items/{item['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Step removed"

    public = await client.get("/api/v1/pages/about/steps")
    assert [entry["title"] for entry in public.json()["items"]] == SEEDED
