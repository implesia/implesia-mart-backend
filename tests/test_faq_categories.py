from httpx import AsyncClient


def _item(
    *,
    label: str = "Orders",
    icon: str = "package_2",
    active: bool = True,
    item_id: str | None = None,
) -> dict:
    body: dict = {"label": label, "icon": icon, "is_active": active}
    if item_id:
        body["id"] = item_id
    return body


def _body(*, active: bool = True) -> dict:
    return {
        "is_active": active,
        "title": "Topics",
        "subtitle": "Browse by subject",
        "all_label": "All questions",
        "all_icon": "grid_view",
        "nav_label": "FAQ categories",
        "items": [_item(), _item(label="Shipping", icon="local_shipping", active=False)],
    }


async def test_public_faq_categories_start_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/faqs/categories")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["items"] == []
    assert "is_active" not in body
    assert "অর্ডার ও রিটার্ন" not in response.text
    assert "বিষয় অনুযায়ী দেখুন" not in response.text
    assert "সব প্রশ্ন" not in response.text


async def test_faq_categories_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/faqs/categories")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "faq-categories-viewer@implesia.com",
            "full_name": "FAQ Categories Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "faq-categories-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/faqs/categories",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_faq_categories(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/faqs/categories",
        headers=auth_headers,
        json={**_body(), "items": [_item(label="   ")]},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Every category needs a name."

    saved = await client.patch(
        "/api/v1/admin/pages/faqs/categories",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Topics"
    assert saved.json()["items"][1]["is_active"] is False
    kept = saved.json()["items"][0]["id"]

    public = await client.get("/api/v1/pages/faqs/categories")
    assert public.json()["all_label"] == "All questions"
    assert [item["label"] for item in public.json()["items"]] == ["Orders"]
    assert "is_active" not in public.json()

    again = await client.patch(
        "/api/v1/admin/pages/faqs/categories",
        headers=auth_headers,
        json={**_body(), "items": [_item(label="Returns", item_id=kept)]},
    )
    assert again.status_code == 200, again.text
    assert again.json()["items"][0]["id"] == kept
    assert again.json()["items"][0]["label"] == "Returns"

    hidden = await client.patch(
        "/api/v1/admin/pages/faqs/categories",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/faqs/categories")
    assert cleared.json()["title"] == ""
    assert cleared.json()["items"] == []

    restored = await client.patch(
        "/api/v1/admin/pages/faqs/categories",
        headers=auth_headers,
        json={**_body(), "items": [_item(label="Returns", item_id=kept)]},
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/faqs/categories")
    assert shown.json()["title"] == "Topics"
    assert shown.json()["items"][0]["label"] == "Returns"
