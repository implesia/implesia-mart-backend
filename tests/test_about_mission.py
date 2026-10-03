from httpx import AsyncClient

VISION = "আমাদের ভিশন"
MISSION = "আমাদের মিশন"


async def test_public_about_mission_seeds_both_cards(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/about/mission")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["key"] for item in items] == ["vision", "mission"]
    assert items[0]["title"] == VISION
    assert items[0]["icon"] == "visibility"
    assert items[1]["title"] == MISSION
    assert items[1]["icon"] == "rocket_launch"
    assert "is_active" not in items[0]


async def test_about_mission_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/about/mission")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "about-mission-viewer@implesia.com",
            "full_name": "About Mission Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "about-mission-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/about/mission/vision",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"title": "Nope", "description": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_hide_and_restore_a_card(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    listed = await client.get("/api/v1/admin/pages/about/mission", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    vision = next(item for item in listed.json() if item["key"] == "vision")

    blank = await client.patch(
        "/api/v1/admin/pages/about/mission/vision",
        headers=auth_headers,
        json={"title": "   ", "description": "   "},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    missing = await client.patch(
        "/api/v1/admin/pages/about/mission/nope",
        headers=auth_headers,
        json={"title": "Nope", "description": "Nope"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Card not found"

    hidden = await client.patch(
        "/api/v1/admin/pages/about/mission/vision",
        headers=auth_headers,
        json={
            "icon": "  ",
            "title": f"  {vision['title']}  ",
            "description": vision["description"],
            "is_active": False,
        },
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["is_active"] is False
    assert hidden.json()["icon"] == "verified"
    assert hidden.json()["title"] == vision["title"]

    public = await client.get("/api/v1/pages/about/mission")
    assert [item["key"] for item in public.json()["items"]] == ["mission"]

    restored = await client.patch(
        "/api/v1/admin/pages/about/mission/vision",
        headers=auth_headers,
        json={
            "icon": "visibility",
            "title": vision["title"],
            "description": vision["description"],
            "is_active": True,
        },
    )
    assert restored.status_code == 200, restored.text
    public = await client.get("/api/v1/pages/about/mission")
    assert [item["title"] for item in public.json()["items"]] == [VISION, MISSION]
    assert public.json()["items"][0]["icon"] == "visibility"
