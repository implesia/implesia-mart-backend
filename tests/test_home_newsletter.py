from httpx import AsyncClient

SEEDED = ["ফ্ল্যাশ অফার আপডেট", "নতুন গ্যাজেট আগে জানুন", "স্প্যাম নেই"]


async def test_public_newsletter_seeds_the_home_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/home/newsletter")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eyebrow"] == "অফার ও আপডেট"
    assert body["title"] == "নতুন অফার মিস করবেন না"
    assert body["placeholder"] == "আপনার ইমেইল লিখুন"
    assert body["cta"] == "সাবস্ক্রাইব"
    assert [perk["label"] for perk in body["perks"]] == SEEDED
    assert body["perks"][0]["icon"] == "local_offer"
    assert "is_active" not in body["perks"][0]


async def test_newsletter_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/newsletter")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "newsletter-viewer@implesia.com",
            "full_name": "Newsletter Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "newsletter-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/home/newsletter/perks",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"label": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_perk(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.services.home import newsletter_service

    monkeypatch.setattr(newsletter_service, "MAX_PERKS", 3)
    blocked = await client.post(
        "/api/v1/admin/home/newsletter/perks",
        headers=auth_headers,
        json={"label": "Extra"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 12 perks"
    monkeypatch.setattr(newsletter_service, "MAX_PERKS", 12)

    created = await client.post(
        "/api/v1/admin/home/newsletter/perks",
        headers=auth_headers,
        json={"icon": "verified", "label": "  Checked  ", "is_active": False},
    )
    assert created.status_code == 201, created.text
    perk = created.json()
    assert perk["label"] == "Checked"
    assert perk["icon"] == "verified"
    assert perk["is_active"] is False

    public = await client.get("/api/v1/home/newsletter")
    assert [item["label"] for item in public.json()["perks"]] == SEEDED

    listed = await client.get("/api/v1/admin/home/newsletter", headers=auth_headers)
    ids = [item["id"] for item in listed.json()["perks"]]
    moved = await client.put(
        "/api/v1/admin/home/newsletter/perks/order",
        headers=auth_headers,
        json={"ids": [perk["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["perks"][0]["id"] == perk["id"]

    incomplete = await client.put(
        "/api/v1/admin/home/newsletter/perks/order",
        headers=auth_headers,
        json={"ids": [perk["id"]]},
    )
    assert incomplete.status_code == 422

    blank = await client.post(
        "/api/v1/admin/home/newsletter/perks",
        headers=auth_headers,
        json={"label": "   "},
    )
    assert blank.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/home/newsletter/perks/{perk['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Perk removed"

    again = await client.get("/api/v1/home/newsletter")
    assert [item["label"] for item in again.json()["perks"]] == SEEDED
