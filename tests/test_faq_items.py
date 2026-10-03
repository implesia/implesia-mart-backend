from httpx import AsyncClient


async def _category(client: AsyncClient, headers: dict[str, str]) -> str:
    saved = await client.patch(
        "/api/v1/admin/pages/faqs/categories",
        headers=headers,
        json={
            "is_active": True,
            "title": "Topics",
            "items": [{"label": "Orders", "icon": "package_2", "is_active": True}],
        },
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["items"][0]["id"]


def _body(
    category_id: str,
    *,
    question: str = "How do I track an order?",
    active: bool = True,
) -> dict:
    return {
        "category_id": category_id,
        "question": question,
        "answer": "Use the orders page.",
        "is_active": active,
    }


async def test_public_faq_items_start_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/faqs/items")
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert "আমার অর্ডার কীভাবে ট্র্যাক করব" not in response.text
    assert "রিটার্ন পলিসি কী" not in response.text


async def test_faq_items_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/faqs/items")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "faq-items-viewer@implesia.com",
            "full_name": "FAQ Items Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "faq-items-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/faqs/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body("00000000-0000-0000-0000-000000000001"),
    )
    assert denied.status_code == 403


async def test_editor_creates_hides_and_removes_a_faq_question(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category_id = await _category(client, auth_headers)

    blank = await client.post(
        "/api/v1/admin/pages/faqs/items",
        headers=auth_headers,
        json=_body(category_id, question="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Question is required."

    missing = await client.post(
        "/api/v1/admin/pages/faqs/items",
        headers=auth_headers,
        json=_body("00000000-0000-0000-0000-000000000001"),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["message"] == "Choose a category."

    created = await client.post(
        "/api/v1/admin/pages/faqs/items",
        headers=auth_headers,
        json=_body(category_id),
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    assert created.json()["question"] == "How do I track an order?"

    second = await client.post(
        "/api/v1/admin/pages/faqs/items",
        headers=auth_headers,
        json=_body(category_id, question="Can I cancel?"),
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    public = await client.get("/api/v1/pages/faqs/items")
    assert [item["question"] for item in public.json()["items"]] == [
        "How do I track an order?",
        "Can I cancel?",
    ]
    assert "is_active" not in public.json()["items"][0]

    hidden = await client.patch(
        f"/api/v1/admin/pages/faqs/items/{item_id}",
        headers=auth_headers,
        json=_body(category_id, active=False),
    )
    assert hidden.status_code == 200, hidden.text
    shown = await client.get("/api/v1/pages/faqs/items")
    assert [item["question"] for item in shown.json()["items"]] == ["Can I cancel?"]

    ordered = await client.put(
        "/api/v1/admin/pages/faqs/items/order",
        headers=auth_headers,
        json={"ids": [second_id, item_id]},
    )
    assert ordered.status_code == 200, ordered.text
    assert [item["id"] for item in ordered.json()["items"]] == [second_id, item_id]

    removed = await client.delete(
        f"/api/v1/admin/pages/faqs/items/{item_id}",
        headers=auth_headers,
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["message"] == "Question removed"
    await client.delete(f"/api/v1/admin/pages/faqs/items/{second_id}", headers=auth_headers)
    cleared = await client.get("/api/v1/pages/faqs/items")
    assert cleared.json()["items"] == []
