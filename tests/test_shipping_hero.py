from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    title: str = "Delivery, COD, and a 3-day return",
) -> dict:
    return {
        "is_active": active,
        "eyebrow": "Shipping",
        "title": title,
        "subtitle": "Dhaka in 24 to 48 hours.",
    }


async def test_public_shipping_hero_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/shipping/hero")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eyebrow"] == ""
    assert body["title"] == ""
    assert body["subtitle"] == ""
    assert "is_active" not in body
    assert "ডেলিভারি, COD ও ৩ দিন রিটার্ন" not in response.text
    assert "ঢাকায় ২৪–৪৮ ঘণ্টা" not in response.text


async def test_shipping_hero_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/shipping/hero")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "shipping-hero-viewer@implesia.com",
            "full_name": "Shipping Hero Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shipping-hero-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/shipping/hero",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_shipping_hero(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/shipping/hero",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    saved = await client.patch(
        "/api/v1/admin/pages/shipping/hero",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["eyebrow"] == "Shipping"
    assert saved.json()["title"] == "Delivery, COD, and a 3-day return"

    public = await client.get("/api/v1/pages/shipping/hero")
    assert public.json()["title"] == "Delivery, COD, and a 3-day return"
    assert public.json()["subtitle"] == "Dhaka in 24 to 48 hours."
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/shipping/hero",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/shipping/hero")
    assert cleared.json()["title"] == ""
    assert cleared.json()["eyebrow"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/shipping/hero",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/shipping/hero")
    assert shown.json()["title"] == "Delivery, COD, and a 3-day return"
