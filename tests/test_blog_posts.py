from httpx import AsyncClient


def _category_body() -> dict:
    return {"is_active": True, "items": [{"label": "Guides", "is_active": True}]}


def _post(*, category_id: str, slug: str = "power-bank-guide", active: bool = True) -> dict:
    return {
        "is_active": active,
        "slug": slug,
        "title": "Power bank guide",
        "excerpt": "How to choose one.",
        "category_id": category_id,
        "cover_image": "/uploads/cover.webp",
        "cover_alt": "A power bank",
        "author": "Mart team",
        "author_role": "Editor",
        "published_at": "3 Oct 2026",
        "read_time": "4 min",
        "tags": ["guide"],
        "related_product_slugs": [],
        "blocks": [
            {"type": "paragraph", "text": "Start here.", "is_active": True},
            {"type": "heading", "text": "Hidden", "is_active": False},
        ],
    }


async def _category_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    saved = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json=_category_body(),
    )
    assert saved.status_code == 200, saved.text
    return str(saved.json()["items"][0]["id"])


async def test_public_blog_posts_start_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/blogs/posts")
    assert response.status_code == 200, response.text
    assert response.json() == {"posts": []}
    assert "is_active" not in response.text
    assert "সঠিক পাওয়ার ব্যাংক" not in response.text
    assert "AI ফেস ট্র্যাকিং" not in response.text


async def test_blog_posts_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/blogs/posts")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "blog-posts-viewer@implesia.com",
            "full_name": "Blog Posts Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "blog-posts-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/blogs/posts",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={},
    )
    assert denied.status_code == 403


async def test_editor_creates_hides_reorders_and_deletes_a_post(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category_id = await _category_id(client, auth_headers)
    blank = await client.post(
        "/api/v1/admin/pages/blogs/posts",
        headers=auth_headers,
        json={**_post(category_id=category_id), "title": "  "},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    bad_slug = await client.post(
        "/api/v1/admin/pages/blogs/posts",
        headers=auth_headers,
        json={**_post(category_id=category_id), "slug": "Not A Slug"},
    )
    assert bad_slug.status_code == 422

    missing_category = await client.post(
        "/api/v1/admin/pages/blogs/posts",
        headers=auth_headers,
        json={**_post(category_id=category_id), "category_id": ""},
    )
    assert missing_category.status_code == 422
    assert missing_category.json()["error"]["message"] == "Choose a category."

    created = await client.post(
        "/api/v1/admin/pages/blogs/posts",
        headers=auth_headers,
        json=_post(category_id=category_id),
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]
    assert created.json()["blocks"][1]["is_active"] is False

    duplicate = await client.post(
        "/api/v1/admin/pages/blogs/posts",
        headers=auth_headers,
        json=_post(category_id=category_id, slug="another-guide"),
    )
    assert duplicate.status_code == 201, duplicate.text
    taken = await client.patch(
        f"/api/v1/admin/pages/blogs/posts/{duplicate.json()['id']}",
        headers=auth_headers,
        json=_post(category_id=category_id, slug="power-bank-guide"),
    )
    assert taken.status_code == 409
    assert taken.json()["error"]["message"] == "Another article already uses this slug."

    public = await client.get("/api/v1/pages/blogs/posts")
    assert [item["slug"] for item in public.json()["posts"]] == [
        "power-bank-guide",
        "another-guide",
    ]
    assert public.json()["posts"][0]["blocks"] == [
        {
            "id": created.json()["blocks"][0]["id"],
            "type": "paragraph",
            "text": "Start here.",
            "title": "",
            "variant": "tip",
            "items": [],
        }
    ]
    detail = await client.get("/api/v1/pages/blogs/posts/power-bank-guide")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Power bank guide"

    hidden = await client.patch(
        f"/api/v1/admin/pages/blogs/posts/{post_id}",
        headers=auth_headers,
        json=_post(category_id=category_id, active=False),
    )
    assert hidden.status_code == 200, hidden.text
    gone = await client.get("/api/v1/pages/blogs/posts/power-bank-guide")
    assert gone.status_code == 404

    order = await client.put(
        "/api/v1/admin/pages/blogs/posts/order",
        headers=auth_headers,
        json={"ids": [duplicate.json()["id"], post_id]},
    )
    assert order.status_code == 200, order.text
    assert [item["slug"] for item in order.json()["posts"]] == [
        "another-guide",
        "power-bank-guide",
    ]

    cleared = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json={"is_active": True, "items": []},
    )
    assert cleared.status_code == 200, cleared.text
    kept = await client.get("/api/v1/admin/pages/blogs/posts", headers=auth_headers)
    assert len(kept.json()["posts"]) == 2

    removed = await client.delete(
        f"/api/v1/admin/pages/blogs/posts/{post_id}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    removed_other = await client.delete(
        f"/api/v1/admin/pages/blogs/posts/{duplicate.json()['id']}",
        headers=auth_headers,
    )
    assert removed_other.status_code == 200
    empty = await client.get("/api/v1/pages/blogs/posts")
    assert empty.json() == {"posts": []}
