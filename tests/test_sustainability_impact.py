from httpx import AsyncClient

SEEDED = ["ক্যাশ অন ডেলিভারি", "ইজি রিটার্ন", "পাঠানোর আগে যাচাই", "প্লাস্টিক প্যাক"]


async def test_public_sustainability_impact_seeds_the_habits(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/sustainability/impact")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kicker"] == "আমাদের অভ্যাস"
    assert body["title"] == "যা আমরা প্রতিদিন মেনে চলি"
    assert [item["label"] for item in body["items"]] == SEEDED
    assert body["items"][0]["icon"] == "payments"
    assert body["items"][0]["value"] == "COD"
    assert "is_active" not in body["items"][0]


async def test_sustainability_impact_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/sustainability/impact")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "sustain-impact-viewer@implesia.com",
            "full_name": "Sustain Impact Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "sustain-impact-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/sustainability/impact/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"value": "Nope", "label": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_stat(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.services.sustainability import impact_service

    monkeypatch.setattr(impact_service, "MAX_STATS", 4)
    blocked = await client.post(
        "/api/v1/admin/pages/sustainability/impact/items",
        headers=auth_headers,
        json={"value": "Extra", "label": "Extra"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 12 stats"
    monkeypatch.setattr(impact_service, "MAX_STATS", 12)

    blank = await client.post(
        "/api/v1/admin/pages/sustainability/impact/items",
        headers=auth_headers,
        json={"value": "   ", "label": "Kept"},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Value is required."

    created = await client.post(
        "/api/v1/admin/pages/sustainability/impact/items",
        headers=auth_headers,
        json={"icon": "  ", "value": "  ০৫  ", "label": "  Stat check  ", "is_active": False},
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["value"] == "০৫"
    assert item["label"] == "Stat check"
    assert item["icon"] == "verified"
    assert item["is_active"] is False

    public = await client.get("/api/v1/pages/sustainability/impact")
    assert [entry["label"] for entry in public.json()["items"]] == SEEDED

    listed = await client.get("/api/v1/admin/pages/sustainability/impact", headers=auth_headers)
    ids = [entry["id"] for entry in listed.json()["items"]]
    moved = await client.put(
        "/api/v1/admin/pages/sustainability/impact/items/order",
        headers=auth_headers,
        json={"ids": [item["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["items"][0]["id"] == item["id"]

    incomplete = await client.put(
        "/api/v1/admin/pages/sustainability/impact/items/order",
        headers=auth_headers,
        json={"ids": [item["id"]]},
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["message"] == "Send every stat in the new order"

    missing = await client.delete(
        "/api/v1/admin/pages/sustainability/impact/items/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Stat not found"

    removed = await client.delete(
        f"/api/v1/admin/pages/sustainability/impact/items/{item['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Stat removed"

    public = await client.get("/api/v1/pages/sustainability/impact")
    assert [entry["label"] for entry in public.json()["items"]] == SEEDED
