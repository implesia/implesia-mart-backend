from httpx import AsyncClient

SEEDED = ["ক্যাটাগরি", "জেলায় ডেলিভারি", "ক্যাশ অন ডেলিভারি", "ইজি রিটার্ন"]


async def test_public_about_stats_seed_the_bar(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/about/stats")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["label"] for item in body["items"]] == SEEDED
    assert body["items"][0]["icon"] == "category"
    assert body["items"][0]["value"] == "২"
    assert body["items"][2]["value"] == "COD"
    assert "is_active" not in body["items"][0]


async def test_about_stats_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/about/stats")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "about-stats-viewer@implesia.com",
            "full_name": "About Stats Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "about-stats-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/about/stats",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"value": "1", "label": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_stat(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.services.about import stats_service

    monkeypatch.setattr(stats_service, "MAX_STATS", 4)
    blocked = await client.post(
        "/api/v1/admin/pages/about/stats",
        headers=auth_headers,
        json={"value": "9", "label": "Extra"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 12 stats"
    monkeypatch.setattr(stats_service, "MAX_STATS", 12)

    created = await client.post(
        "/api/v1/admin/pages/about/stats",
        headers=auth_headers,
        json={"icon": "verified", "value": "  ৭  ", "label": "  Checked  ", "is_active": False},
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["value"] == "৭"
    assert item["label"] == "Checked"
    assert item["icon"] == "verified"
    assert item["is_active"] is False

    public = await client.get("/api/v1/pages/about/stats")
    assert [entry["label"] for entry in public.json()["items"]] == SEEDED

    listed = await client.get("/api/v1/admin/pages/about/stats", headers=auth_headers)
    ids = [entry["id"] for entry in listed.json()]
    moved = await client.put(
        "/api/v1/admin/pages/about/stats/order",
        headers=auth_headers,
        json={"ids": [item["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()[0]["id"] == item["id"]

    incomplete = await client.put(
        "/api/v1/admin/pages/about/stats/order",
        headers=auth_headers,
        json={"ids": [item["id"]]},
    )
    assert incomplete.status_code == 422

    blank = await client.post(
        "/api/v1/admin/pages/about/stats",
        headers=auth_headers,
        json={"value": "   ", "label": "Label"},
    )
    assert blank.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/pages/about/stats/{item['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Stat removed"

    again = await client.get("/api/v1/pages/about/stats")
    assert [entry["label"] for entry in again.json()["items"]] == SEEDED
