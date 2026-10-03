from httpx import AsyncClient


def _body(*, active: bool = True, title: str = "How we keep order details") -> dict:
    return {
        "is_active": active,
        "eyebrow": "Privacy",
        "title": title,
        "subtitle": "Name, phone, and address are used for delivery and support.",
        "updated_label": "Last updated:",
        "last_updated": "September 2026",
    }


async def test_public_privacy_hero_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/privacy/hero")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eyebrow"] == ""
    assert body["title"] == ""
    assert body["subtitle"] == ""
    assert body["updated_label"] == ""
    assert body["last_updated"] == ""
    assert "is_active" not in body
    assert "অর্ডারের তথ্য কীভাবে রাখি" not in response.text
    assert "চেকআউট ও সাপোর্টে যে নাম" not in response.text
    assert "সর্বশেষ আপডেট:" not in response.text


async def test_privacy_hero_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/privacy/hero")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "privacy-hero-viewer@implesia.com",
            "full_name": "Privacy Hero Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "privacy-hero-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/privacy/hero",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_and_hides_the_privacy_hero(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/privacy/hero",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    saved = await client.patch(
        "/api/v1/admin/pages/privacy/hero",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "How we keep order details"
    assert saved.json()["last_updated"] == "September 2026"

    public = await client.get("/api/v1/pages/privacy/hero")
    assert public.json()["title"] == "How we keep order details"
    assert public.json()["updated_label"] == "Last updated:"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/privacy/hero",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/privacy/hero")
    assert cleared.json()["title"] == ""
    assert cleared.json()["last_updated"] == ""
