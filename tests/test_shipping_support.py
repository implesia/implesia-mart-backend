from httpx import AsyncClient


def _body(*, active: bool = True, title: str = "Still need help?") -> dict:
    return {
        "is_active": active,
        "icon": "support_agent",
        "nav_label": "Support",
        "title": title,
        "subtitle": "Ask about an order, delivery, or a return.",
        "email": "hello@implesia.com",
        "phone": "+880 1516-527932",
        "primary_label": "Contact",
        "primary_href": "/contact-us",
        "secondary_label": "WhatsApp",
        "secondary_href": "https://wa.me/8801516527932",
    }


async def test_public_shipping_support_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/shipping/support")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["subtitle"] == ""
    assert body["email"] == ""
    assert body["primary_label"] == ""
    assert "is_active" not in body
    assert "এখনও সাহায্য দরকার?" not in response.text
    assert "অর্ডার, ডেলিভারি বা রিটার্ন" not in response.text
    assert "হোয়াটসঅ্যাপ" not in response.text


async def test_shipping_support_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/shipping/support")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "shipping-support-viewer@implesia.com",
            "full_name": "Shipping Support Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shipping-support-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/shipping/support",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_rejects_a_bad_link(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/shipping/support",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    blocked = await client.patch(
        "/api/v1/admin/pages/shipping/support",
        headers=auth_headers,
        json={**_body(), "primary_href": "javascript:alert(1)"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "Button link is not allowed"

    saved = await client.patch(
        "/api/v1/admin/pages/shipping/support",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Still need help?"
    assert saved.json()["primary_href"] == "/contact-us"

    public = await client.get("/api/v1/pages/shipping/support")
    assert public.json()["title"] == "Still need help?"
    assert public.json()["secondary_label"] == "WhatsApp"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/shipping/support",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/shipping/support")
    assert cleared.json()["title"] == ""
    assert cleared.json()["email"] == ""
