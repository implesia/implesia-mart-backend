from httpx import AsyncClient

TITLE = "কোয়ালিটি চেক করা গ্যাজেট ও গর্জিয়াস ড্রেস"
SUBTITLE = "হাতে পেয়ে দেখে তারপর ক্যাশ অন ডেলিভারি — সারাদেশে।"


def _body(*, title: str = TITLE) -> dict[str, object]:
    return {
        "title": title,
        "subtitle": SUBTITLE,
        "primary_cta": {"label": "সব প্রোডাক্ট", "href": "/products"},
        "secondary_cta": {"label": "যোগাযোগ", "href": "/contact-us"},
    }


async def test_public_sustainability_cta_seeds_the_closing_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/sustainability/cta")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == TITLE
    assert body["subtitle"] == SUBTITLE
    assert body["primary_cta"]["label"] == "সব প্রোডাক্ট"
    assert body["primary_cta"]["href"] == "/products"
    assert body["secondary_cta"]["label"] == "যোগাযোগ"
    assert body["secondary_cta"]["href"] == "/contact-us"


async def test_sustainability_cta_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/sustainability/cta")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "sustain-cta-viewer@implesia.com",
            "full_name": "Sustain Cta Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "sustain-cta-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/sustainability/cta",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(title="Nope"),
    )
    assert denied.status_code == 403


async def test_editor_can_update_and_restore_the_cta(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/sustainability/cta",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    updated = await client.patch(
        "/api/v1/admin/pages/sustainability/cta",
        headers=auth_headers,
        json={
            "title": "Updated heading",
            "subtitle": "Updated line",
            "primary_cta": {"label": "", "href": ""},
            "secondary_cta": {"label": "Write", "href": "https://example.com/contact"},
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["title"] == "Updated heading"
    assert body["primary_cta"]["label"] == ""
    assert body["secondary_cta"]["href"] == "https://example.com/contact"

    public = await client.get("/api/v1/pages/sustainability/cta")
    assert public.json()["title"] == "Updated heading"
    assert public.json()["primary_cta"]["label"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/sustainability/cta",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["title"] == TITLE
    assert restored.json()["secondary_cta"]["label"] == "যোগাযোগ"
