from httpx import AsyncClient


def _body(*, active: bool = True, heading: str = "Who we share with") -> dict:
    return {
        "is_active": active,
        "icon": "share",
        "nav_label": "Sharing",
        "heading": heading,
        "body": "We do not sell personal details. Limited details go to delivery partners.",
        "chips": [{"id": "chip-1", "label": "Courier", "is_active": True}],
    }


async def test_public_privacy_sharing_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/privacy/sharing")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["body"] == ""
    assert body["chips"] == []
    assert "is_active" not in body
    assert "তথ্য শেয়ারিং" not in response.text
    assert "আমরা আপনার ব্যক্তিগত তথ্য মার্কেটিংয়ের জন্য" not in response.text
    assert "কুরিয়ার / লজিস্টিক্স" not in response.text
    assert "পেমেন্ট সহায়ক" not in response.text
    assert "হোস্টিং / ক্লাউড" not in response.text


async def test_privacy_sharing_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/privacy/sharing")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "privacy-sharing-viewer@implesia.com",
            "full_name": "Privacy Sharing Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "privacy-sharing-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/privacy/sharing",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_rejects_a_blank_chip(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/privacy/sharing",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    empty = await client.patch(
        "/api/v1/admin/pages/privacy/sharing",
        headers=auth_headers,
        json={**_body(), "chips": [{"label": "   "}]},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == (
        "Every chip needs a label, or remove the empty ones."
    )

    saved = await client.patch(
        "/api/v1/admin/pages/privacy/sharing",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["heading"] == "Who we share with"
    assert saved.json()["chips"][0]["label"] == "Courier"

    public = await client.get("/api/v1/pages/privacy/sharing")
    assert public.json()["heading"] == "Who we share with"
    assert public.json()["chips"][0]["label"] == "Courier"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/privacy/sharing",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/privacy/sharing")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["chips"] == []
