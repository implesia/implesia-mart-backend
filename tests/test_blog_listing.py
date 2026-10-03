from httpx import AsyncClient


def _body(*, active: bool = True, heading: str = "Latest") -> dict:
    return {
        "is_active": active,
        "heading": heading,
        "all_label": "All",
        "count_suffix": " articles",
        "empty_message": "Nothing in this category yet.",
        "featured_label": "Featured",
        "read_label": "Read",
        "read_suffix": "read",
        "tabs_label": "Categories",
    }


async def test_public_blog_listing_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/blogs/listing")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["all_label"] == ""
    assert body["count_suffix"] == ""
    assert body["empty_message"] == ""
    assert "is_active" not in body
    assert "সর্বশেষ আর্টিকেল" not in response.text
    assert "টি আর্টিকেল" not in response.text
    assert "ব্লগ ক্যাটাগরি" not in response.text


async def test_blog_listing_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/blogs/listing")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "blog-listing-viewer@implesia.com",
            "full_name": "Blog Listing Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "blog-listing-viewer@implesia.com",
            "password": "viewer-passphrase",
        },
    )
    denied = await client.patch(
        "/api/v1/admin/pages/blogs/listing",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_blog_listing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.patch(
        "/api/v1/admin/pages/blogs/listing",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["heading"] == "Latest"
    assert saved.json()["count_suffix"] == " articles"

    public = await client.get("/api/v1/pages/blogs/listing")
    assert public.json()["heading"] == "Latest"
    assert public.json()["read_label"] == "Read"

    hidden = await client.patch(
        "/api/v1/admin/pages/blogs/listing",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/blogs/listing")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["read_label"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/blogs/listing",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/blogs/listing")
    assert shown.json()["heading"] == "Latest"
    assert shown.json()["all_label"] == "All"
