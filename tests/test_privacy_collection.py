from httpx import AsyncClient


def _body(*, active: bool = True, heading: str = "Information we keep") -> dict:
    return {
        "is_active": active,
        "icon": "database",
        "nav_label": "Collection",
        "heading": heading,
        "intro": "Only what is needed to deliver and support an order.",
        "cards": [
            {
                "id": "card-1",
                "icon": "person_search",
                "title": "Personal details",
                "description": "Name, phone, email, and shipping address.",
                "is_active": True,
            }
        ],
    }


async def test_public_privacy_collection_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/privacy/collection")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["intro"] == ""
    assert body["cards"] == []
    assert "is_active" not in body
    assert "যে তথ্য আমরা সংগ্রহ করি" not in response.text
    assert "সেবা দেওয়ার জন্য প্রয়োজনীয় তথ্যই" not in response.text
    assert "ব্যক্তিগত তথ্য" not in response.text
    assert "প্রযুক্তিগত তথ্য" not in response.text


async def test_privacy_collection_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/privacy/collection")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "privacy-collection-viewer@implesia.com",
            "full_name": "Privacy Collection Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "privacy-collection-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/privacy/collection",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_rejects_a_blank_card(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/privacy/collection",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    empty = await client.patch(
        "/api/v1/admin/pages/privacy/collection",
        headers=auth_headers,
        json={**_body(), "cards": [{"title": "   "}]},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == "Every card needs a title."

    saved = await client.patch(
        "/api/v1/admin/pages/privacy/collection",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["heading"] == "Information we keep"
    assert saved.json()["cards"][0]["title"] == "Personal details"

    public = await client.get("/api/v1/pages/privacy/collection")
    assert public.json()["heading"] == "Information we keep"
    assert public.json()["cards"][0]["description"].startswith("Name, phone")
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/privacy/collection",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/privacy/collection")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["cards"] == []
