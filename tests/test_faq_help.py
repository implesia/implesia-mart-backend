from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    title: str = "Still need help?",
    href: str = "/contact-us",
) -> dict:
    return {
        "is_active": active,
        "title": title,
        "subtitle": "Call or message us about an order.",
        "email": "hello@example.com",
        "phone": "+880 1700-000000",
        "primary_label": "Contact",
        "primary_href": href,
        "secondary_label": "WhatsApp",
        "secondary_href": "https://wa.me/8801700000000",
    }


async def test_public_faq_help_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/faqs/help")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["subtitle"] == ""
    assert body["email"] == ""
    assert body["phone"] == ""
    assert "is_active" not in body
    assert "এখনও সাহায্য দরকার?" not in response.text
    assert "অর্ডার, ডেলিভারি বা প্রোডাক্ট" not in response.text


async def test_faq_help_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/faqs/help")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "faq-help-viewer@implesia.com",
            "full_name": "FAQ Help Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "faq-help-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/faqs/help",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_faq_help(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/faqs/help",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    blocked = await client.patch(
        "/api/v1/admin/pages/faqs/help",
        headers=auth_headers,
        json=_body(href="javascript:alert(1)"),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "Button link is not allowed"

    saved = await client.patch(
        "/api/v1/admin/pages/faqs/help",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Still need help?"
    assert saved.json()["primary_label"] == "Contact"

    public = await client.get("/api/v1/pages/faqs/help")
    assert public.json()["title"] == "Still need help?"
    assert public.json()["subtitle"] == "Call or message us about an order."
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/faqs/help",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/faqs/help")
    assert cleared.json()["title"] == ""
    assert cleared.json()["email"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/faqs/help",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/faqs/help")
    assert shown.json()["title"] == "Still need help?"
