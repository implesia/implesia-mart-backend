from httpx import AsyncClient

TITLE = "আজই খুঁজে নিন আপনার প্রয়োজনীয় প্রোডাক্ট"
SUBTITLE = "গ্যাজেট হোক বা গর্জিয়াস ড্রেস — হাতে পেয়ে দেখে তারপর ক্যাশ অন ডেলিভারি।"


def _body(*, active: bool, title: str = TITLE) -> dict[str, object]:
    return {
        "is_active": active,
        "title": title,
        "subtitle": SUBTITLE,
        "primary_cta": {"label": "সব প্রোডাক্ট", "href": "/products"},
        "secondary_cta": {"label": "যোগাযোগ", "href": "/contact-us"},
    }


async def test_public_about_cta_seeds_the_closing_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/about/cta")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == TITLE
    assert body["primary_cta"]["label"] == "সব প্রোডাক্ট"
    assert body["primary_cta"]["href"] == "/products"
    assert body["secondary_cta"]["href"] == "/contact-us"
    assert "is_active" not in body


async def test_about_cta_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/about/cta")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "about-cta-viewer@implesia.com",
            "full_name": "About Cta Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "about-cta-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/about/cta",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_can_hide_and_restore_the_cta(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/about/cta",
        headers=auth_headers,
        json=_body(active=True, title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    hidden = await client.patch(
        "/api/v1/admin/pages/about/cta",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["is_active"] is False
    assert hidden.json()["title"] == TITLE

    public = await client.get("/api/v1/pages/about/cta")
    assert public.json()["title"] == ""
    assert public.json()["primary_cta"]["label"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/about/cta",
        headers=auth_headers,
        json=_body(active=True),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_active"] is True

    public = await client.get("/api/v1/pages/about/cta")
    assert public.json()["title"] == TITLE
    assert public.json()["secondary_cta"]["label"] == "যোগাযোগ"
