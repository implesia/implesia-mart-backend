from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    body: str = "Delivery inside Dhaka usually takes 24 to 48 hours.",
) -> dict:
    return {"is_active": active, "eyebrow": "Important", "body": body}


async def test_public_faq_callout_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/faqs/callout")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eyebrow"] == ""
    assert body["body"] == ""
    assert "is_active" not in body
    assert "গুরুত্বপূর্ণ তথ্য" not in response.text
    assert "ঢাকার ভেতরে সাধারণত" not in response.text


async def test_faq_callout_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/faqs/callout")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "faq-callout-viewer@implesia.com",
            "full_name": "FAQ Callout Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "faq-callout-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/faqs/callout",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_faq_callout(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/faqs/callout",
        headers=auth_headers,
        json=_body(body="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Note is required."

    saved = await client.patch(
        "/api/v1/admin/pages/faqs/callout",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["eyebrow"] == "Important"
    assert saved.json()["body"] == "Delivery inside Dhaka usually takes 24 to 48 hours."

    public = await client.get("/api/v1/pages/faqs/callout")
    assert public.json()["body"] == "Delivery inside Dhaka usually takes 24 to 48 hours."
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/faqs/callout",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/faqs/callout")
    assert cleared.json()["body"] == ""
    assert cleared.json()["eyebrow"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/faqs/callout",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/faqs/callout")
    assert shown.json()["eyebrow"] == "Important"
