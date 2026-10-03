from httpx import AsyncClient


def _body(*, active: bool = True, title: str = "Questions about a product?") -> dict:
    return {
        "is_active": active,
        "title": title,
        "subtitle": "Ask about an order, a size, or stock.",
        "primary_label": "All products",
        "primary_href": "/products",
        "secondary_label": "WhatsApp",
        "secondary_href": "https://wa.me/8801700000000",
    }


async def test_public_blog_cta_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/blogs/cta")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["subtitle"] == ""
    assert body["primary_label"] == ""
    assert body["secondary_href"] == ""
    assert "is_active" not in body
    assert "প্রোডাক্ট নিয়ে জানতে চান?" not in response.text
    assert "কল বা হোয়াটসঅ্যাপে" not in response.text


async def test_blog_cta_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/blogs/cta")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "blog-cta-viewer@implesia.com",
            "full_name": "Blog CTA Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "blog-cta-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/blogs/cta",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_blog_cta(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/blogs/cta",
        headers=auth_headers,
        json=_body(title="  "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    blocked = await client.patch(
        "/api/v1/admin/pages/blogs/cta",
        headers=auth_headers,
        json={**_body(), "secondary_href": "javascript:alert(1)"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "Button link is not allowed"

    saved = await client.patch(
        "/api/v1/admin/pages/blogs/cta",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Questions about a product?"
    assert saved.json()["primary_href"] == "/products"

    public = await client.get("/api/v1/pages/blogs/cta")
    assert public.json()["secondary_label"] == "WhatsApp"
    assert public.json()["secondary_href"] == "https://wa.me/8801700000000"

    hidden = await client.patch(
        "/api/v1/admin/pages/blogs/cta",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    gone = await client.get("/api/v1/pages/blogs/cta")
    assert gone.json()["title"] == ""
    assert gone.json()["primary_label"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/blogs/cta",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/blogs/cta")
    assert shown.json()["title"] == "Questions about a product?"
