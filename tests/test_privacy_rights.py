from httpx import AsyncClient


def _body(*, active: bool = True, heading: str = "Your rights") -> dict:
    return {
        "is_active": active,
        "icon": "gavel",
        "nav_label": "Rights",
        "heading": heading,
        "intro": "You can ask us about the details we keep.",
        "items": [
            {
                "id": "right-1",
                "icon": "visibility",
                "title": "See your details",
                "description": "Ask for a copy of the personal details we hold.",
                "is_active": True,
            }
        ],
        "retention": {
            "is_active": True,
            "title": "How long we keep it",
            "body": "We keep details only as long as the order and the law require.",
        },
        "updates": {
            "is_active": True,
            "title": "Policy updates",
            "body": "Important changes are posted on this page.",
        },
    }


async def test_public_privacy_rights_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/privacy/rights")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["intro"] == ""
    assert body["items"] == []
    assert body["retention"]["title"] == ""
    assert body["updates"]["title"] == ""
    assert "is_active" not in body
    assert "আপনার অধিকার" not in response.text
    assert "আপনার তথ্য সম্পর্কে আপনার নিয়ন্ত্রণ" not in response.text
    assert "দেখার অধিকার" not in response.text
    assert "তথ্য রাখার সময়সীমা" not in response.text
    assert "নীতি আপডেট" not in response.text


async def test_privacy_rights_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/privacy/rights")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "privacy-rights-viewer@implesia.com",
            "full_name": "Privacy Rights Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "privacy-rights-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/privacy/rights",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_rejects_a_blank_right(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/privacy/rights",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    empty = await client.patch(
        "/api/v1/admin/pages/privacy/rights",
        headers=auth_headers,
        json={**_body(), "items": [{"title": "   "}]},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == "Every right needs a title."

    saved = await client.patch(
        "/api/v1/admin/pages/privacy/rights",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["heading"] == "Your rights"
    assert saved.json()["items"][0]["title"] == "See your details"
    assert saved.json()["retention"]["title"] == "How long we keep it"

    public = await client.get("/api/v1/pages/privacy/rights")
    assert public.json()["heading"] == "Your rights"
    assert public.json()["updates"]["title"] == "Policy updates"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/privacy/rights",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/privacy/rights")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["items"] == []
    assert cleared.json()["retention"]["title"] == ""
