from httpx import AsyncClient


def _body(*, active: bool = True, toc_title: str = "In this article") -> dict:
    return {
        "is_active": active,
        "toc_title": toc_title,
        "products_title": "Mentioned products",
        "products_subtitle": "Order what is in stock.",
        "posts_title": "More to read",
        "posts_subtitle": "Related guides",
        "posts_link_label": "All articles",
        "coming_soon_label": "Coming soon",
        "view_label": "View",
        "details_label": "Details",
    }


async def test_public_blog_related_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/blogs/related")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["toc_title"] == ""
    assert body["products_title"] == ""
    assert body["posts_title"] == ""
    assert body["posts_link_label"] == ""
    assert "is_active" not in body
    assert "এই আর্টিকেলে" not in response.text
    assert "আরও পড়ুন" not in response.text
    assert "শীঘ্রই আসছে" not in response.text


async def test_blog_related_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/blogs/related")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "blog-related-viewer@implesia.com",
            "full_name": "Blog Related Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "blog-related-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/blogs/related",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_blog_related(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.patch(
        "/api/v1/admin/pages/blogs/related",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["toc_title"] == "In this article"
    assert saved.json()["view_label"] == "View"

    public = await client.get("/api/v1/pages/blogs/related")
    assert public.json()["posts_title"] == "More to read"
    assert public.json()["posts_link_label"] == "All articles"

    hidden = await client.patch(
        "/api/v1/admin/pages/blogs/related",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    blank = await client.get("/api/v1/pages/blogs/related")
    assert blank.json()["toc_title"] == ""
    assert blank.json()["products_title"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/blogs/related",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/blogs/related")
    assert shown.json()["details_label"] == "Details"
