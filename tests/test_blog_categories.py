from httpx import AsyncClient


def _item(*, label: str = "Guides", active: bool = True, item_id: str | None = None) -> dict:
    body: dict = {"label": label, "is_active": active}
    if item_id:
        body["id"] = item_id
    return body


def _body(*, active: bool = True, label: str = "Guides") -> dict:
    return {"is_active": active, "items": [_item(label=label)]}


async def test_public_blog_categories_start_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/blogs/categories")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert "is_active" not in body
    assert "বায়িং গাইড" not in response.text
    assert "রিভিউ" not in response.text


async def test_blog_categories_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/blogs/categories")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "blog-categories-viewer@implesia.com",
            "full_name": "Blog Categories Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "blog-categories-viewer@implesia.com",
            "password": "viewer-passphrase",
        },
    )
    denied = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_blog_categories(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json={"is_active": True, "items": [_item(label="   ")]},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Every category needs a name."

    duplicate = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json={"is_active": True, "items": [_item(), _item()]},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["message"] == "Each category name can only be used once."

    saved = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json={"is_active": True, "items": [_item(), _item(label="Reviews", active=False)]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["items"][0]["label"] == "Guides"
    assert saved.json()["items"][1]["is_active"] is False
    kept = saved.json()["items"][0]["id"]

    public = await client.get("/api/v1/pages/blogs/categories")
    assert [item["label"] for item in public.json()["items"]] == ["Guides"]

    again = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json={"is_active": True, "items": [_item(label="Buying guides", item_id=kept)]},
    )
    assert again.status_code == 200, again.text
    assert again.json()["items"][0]["id"] == kept
    assert again.json()["items"][0]["label"] == "Buying guides"

    hidden = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json=_body(active=False, label="Buying guides"),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/blogs/categories")
    assert cleared.json()["items"] == []

    restored = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=auth_headers,
        json={"is_active": True, "items": [_item(label="Buying guides", item_id=kept)]},
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/blogs/categories")
    assert shown.json()["items"][0]["label"] == "Buying guides"
