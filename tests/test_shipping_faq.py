from httpx import AsyncClient


def _body(*, active: bool = True) -> dict:
    return {
        "is_active": active,
        "title": "Short questions",
        "items": [
            {
                "id": "faq-1",
                "question": "How do I track an order?",
                "answer": "Use the order number on the order page.",
                "is_active": True,
            }
        ],
        "more_before": "More questions are on the",
        "more_link_label": "FAQ page",
        "more_href": "/faqs",
        "more_after": ".",
    }


async def test_public_shipping_faq_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/shipping/faq")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["items"] == []
    assert body["more_link_label"] == ""
    assert "is_active" not in body
    assert "সংক্ষিপ্ত প্রশ্নোত্তর" not in response.text
    assert "অর্ডার কীভাবে ট্র্যাক করব?" not in response.text
    assert "আরও প্রশ্ন থাকলে" not in response.text
    assert "প্রশ্নোত্তর পেজ" not in response.text


async def test_shipping_faq_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/shipping/faq")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "shipping-faq-viewer@implesia.com",
            "full_name": "Shipping FAQ Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shipping-faq-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/shipping/faq",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_rejects_a_blank_question(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/shipping/faq",
        headers=auth_headers,
        json={**_body(), "items": [{"question": "   ", "answer": ""}]},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Every question needs a question and an answer."

    blocked = await client.patch(
        "/api/v1/admin/pages/shipping/faq",
        headers=auth_headers,
        json={**_body(), "more_href": "javascript:alert(1)"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "Button link is not allowed"

    saved = await client.patch(
        "/api/v1/admin/pages/shipping/faq",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Short questions"
    assert saved.json()["items"][0]["question"] == "How do I track an order?"

    public = await client.get("/api/v1/pages/shipping/faq")
    assert public.json()["items"][0]["question"] == "How do I track an order?"
    assert public.json()["more_link_label"] == "FAQ page"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/shipping/faq",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/shipping/faq")
    assert cleared.json()["title"] == ""
    assert cleared.json()["items"] == []
