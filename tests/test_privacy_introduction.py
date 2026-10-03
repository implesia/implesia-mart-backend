from httpx import AsyncClient


def _body(*, active: bool = True, heading: str = "What this page covers") -> dict:
    return {
        "is_active": active,
        "icon": "info",
        "nav_label": "Introduction",
        "heading": heading,
        "paragraphs": [
            {
                "id": "para-1",
                "text": "We use your name, phone, and address for delivery and support.",
                "is_active": True,
            }
        ],
    }


async def test_public_privacy_introduction_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/privacy/introduction")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["paragraphs"] == []
    assert "is_active" not in body
    assert "ভূমিকা" not in response.text
    assert "ইমপ্লেসিয়া মার্ট থেকে অর্ডার বা যোগাযোগ করলে" not in response.text
    assert "এই পেজে বলা আছে কী সংগ্রহ করি" not in response.text


async def test_privacy_introduction_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/privacy/introduction")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "privacy-intro-viewer@implesia.com",
            "full_name": "Privacy Intro Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "privacy-intro-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/privacy/introduction",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_rejects_a_blank_paragraph(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/privacy/introduction",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    empty = await client.patch(
        "/api/v1/admin/pages/privacy/introduction",
        headers=auth_headers,
        json={**_body(), "paragraphs": [{"text": "   "}]},
    )
    assert empty.status_code == 422
    assert (
        empty.json()["error"]["message"]
        == "Every paragraph needs text, or remove the empty ones."
    )

    saved = await client.patch(
        "/api/v1/admin/pages/privacy/introduction",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["heading"] == "What this page covers"
    assert saved.json()["paragraphs"][0]["text"].startswith("We use your name")

    public = await client.get("/api/v1/pages/privacy/introduction")
    assert public.json()["heading"] == "What this page covers"
    assert public.json()["nav_label"] == "Introduction"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/privacy/introduction",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/privacy/introduction")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["paragraphs"] == []
