from httpx import AsyncClient

TITLE = "অর্ডার বা প্রোডাক্ট নিয়ে সাহায্য লাগলে বলুন"
EYEBROW = "যোগাযোগ"


def _body(*, active: bool = True, title: str = TITLE, primary_href: str | None = None) -> dict:
    return {
        "is_active": active,
        "eyebrow": EYEBROW,
        "title": title,
        "subtitle": (
            "কল বা হোয়াটসঅ্যাপে সরাসরি যোগাযোগ করুন। কর্মঘণ্টায় রিপ্লাই দেওয়ার চেষ্টা করি।"
        ),
        "primary_cta": {
            "label": "হোয়াটসঅ্যাপ",
            "href": primary_href or "https://wa.me/8801516527932",
        },
        "secondary_cta": {"label": "কল করুন", "href": "tel:+8801516527932"},
    }


async def test_public_contact_hero_seeds_the_banner(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/contact/hero")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eyebrow"] == EYEBROW
    assert body["title"] == TITLE
    assert body["primary_cta"]["label"] == "হোয়াটসঅ্যাপ"
    assert body["primary_cta"]["href"].startswith("https://wa.me/8801516527932?text=")
    assert body["secondary_cta"]["href"] == "tel:+8801516527932"
    assert "is_active" not in body


async def test_contact_hero_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/contact/hero")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "contact-hero-viewer@implesia.com",
            "full_name": "Contact Hero Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "contact-hero-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/contact/hero",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_can_hide_and_restore_the_contact_hero(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/contact/hero",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    blocked = await client.patch(
        "/api/v1/admin/pages/contact/hero",
        headers=auth_headers,
        json=_body(primary_href="javascript:alert(1)"),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "Button link is not allowed"

    hidden = await client.patch(
        "/api/v1/admin/pages/contact/hero",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["is_active"] is False
    assert hidden.json()["title"] == TITLE

    public = await client.get("/api/v1/pages/contact/hero")
    assert public.json()["title"] == ""
    assert public.json()["primary_cta"]["label"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/contact/hero",
        headers=auth_headers,
        json=_body(active=True),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_active"] is True
    assert restored.json()["secondary_cta"]["href"] == "tel:+8801516527932"

    public = await client.get("/api/v1/pages/contact/hero")
    assert public.json()["title"] == TITLE
    assert public.json()["eyebrow"] == EYEBROW
