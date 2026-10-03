from httpx import AsyncClient


def _search(*, label: str = "Returns", active: bool = True, item_id: str | None = None) -> dict:
    body: dict = {"label": label, "is_active": active}
    if item_id:
        body["id"] = item_id
    return body


def _body(*, active: bool = True, title: str = "Orders, delivery, and products") -> dict:
    return {
        "is_active": active,
        "eyebrow": "Questions",
        "title": title,
        "subtitle": "Short answers about orders, shipping, and returns.",
        "placeholder": "Search questions",
        "search_label": "Search questions",
        "clear_label": "Clear search",
        "trending_label": "Quick search",
        "trending": [_search(), _search(label="Delivery", active=False)],
    }


async def test_public_faq_hero_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/faqs/hero")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["trending"] == []
    assert "is_active" not in body
    assert "অর্ডার, ডেলিভারি ও প্রোডাক্ট" not in response.text
    assert "দ্রুত খুঁজুন" not in response.text
    assert "কাস্টম ড্রেস" not in response.text


async def test_faq_hero_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/faqs/hero")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "faq-hero-viewer@implesia.com",
            "full_name": "FAQ Hero Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "faq-hero-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/faqs/hero",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_faq_hero(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/faqs/hero",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    empty_search = await client.patch(
        "/api/v1/admin/pages/faqs/hero",
        headers=auth_headers,
        json={**_body(), "trending": [_search(label="   ")]},
    )
    assert empty_search.status_code == 422
    assert empty_search.json()["error"]["message"] == "Every quick search needs a word."

    saved = await client.patch(
        "/api/v1/admin/pages/faqs/hero",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Orders, delivery, and products"
    assert saved.json()["trending"][1]["is_active"] is False
    kept = saved.json()["trending"][0]["id"]

    public = await client.get("/api/v1/pages/faqs/hero")
    assert public.json()["title"] == "Orders, delivery, and products"
    assert [item["label"] for item in public.json()["trending"]] == ["Returns"]
    assert "is_active" not in public.json()

    again = await client.patch(
        "/api/v1/admin/pages/faqs/hero",
        headers=auth_headers,
        json={**_body(), "trending": [_search(label="Track", item_id=kept)]},
    )
    assert again.status_code == 200, again.text
    assert again.json()["trending"][0]["id"] == kept
    assert again.json()["trending"][0]["label"] == "Track"

    hidden = await client.patch(
        "/api/v1/admin/pages/faqs/hero",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/faqs/hero")
    assert cleared.json()["title"] == ""
    assert cleared.json()["trending"] == []

    restored = await client.patch(
        "/api/v1/admin/pages/faqs/hero",
        headers=auth_headers,
        json={**_body(), "trending": [_search(label="Track", item_id=kept)]},
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/faqs/hero")
    assert shown.json()["title"] == "Orders, delivery, and products"
    assert shown.json()["trending"][0]["label"] == "Track"
