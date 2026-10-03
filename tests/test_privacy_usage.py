from httpx import AsyncClient


def _body(*, active: bool = True, heading: str = "How we use information") -> dict:
    return {
        "is_active": active,
        "icon": "query_stats",
        "nav_label": "Use",
        "heading": heading,
        "intro": "We use details only to complete and support an order.",
        "items": [
            {
                "id": "use-1",
                "title": "Complete an order",
                "description": "Processing, packing, and delivery.",
                "is_active": True,
            }
        ],
        "protection": {
            "is_active": True,
            "icon": "verified_user",
            "title": "How we protect it",
            "body": "Access stays limited to the work that needs it.",
            "badges": [
                {
                    "id": "badge-1",
                    "icon": "lock",
                    "label": "Secure connection",
                    "is_active": True,
                }
            ],
        },
    }


async def test_public_privacy_usage_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/privacy/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["intro"] == ""
    assert body["items"] == []
    assert body["protection"]["title"] == ""
    assert body["protection"]["badges"] == []
    assert "is_active" not in body
    assert "তথ্য কীভাবে ব্যবহার করি" not in response.text
    assert "আপনার তথ্য শুধু সেবা ও অভিজ্ঞতা" not in response.text
    assert "অর্ডার সম্পন্ন করা" not in response.text
    assert "তথ্য সুরক্ষা" not in response.text
    assert "সুরক্ষিত সংযোগ" not in response.text


async def test_privacy_usage_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/privacy/usage")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "privacy-usage-viewer@implesia.com",
            "full_name": "Privacy Usage Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "privacy-usage-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/privacy/usage",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_rejects_a_blank_use(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/privacy/usage",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    empty = await client.patch(
        "/api/v1/admin/pages/privacy/usage",
        headers=auth_headers,
        json={**_body(), "items": [{"title": "   "}]},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == (
        "Fill in every use and badge, or remove the empty ones."
    )

    saved = await client.patch(
        "/api/v1/admin/pages/privacy/usage",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["heading"] == "How we use information"
    assert saved.json()["items"][0]["title"] == "Complete an order"
    assert saved.json()["protection"]["title"] == "How we protect it"

    public = await client.get("/api/v1/pages/privacy/usage")
    assert public.json()["heading"] == "How we use information"
    assert public.json()["protection"]["badges"][0]["label"] == "Secure connection"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/privacy/usage",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/privacy/usage")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["items"] == []
    assert cleared.json()["protection"]["title"] == ""
