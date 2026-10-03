from httpx import AsyncClient


def _body(*, active: bool = True, suffix: str = " questions") -> dict:
    return {
        "is_active": active,
        "count_suffix": suffix,
        "empty_title": "No matches",
        "empty_body": "Try another word.",
    }


async def test_public_faq_listing_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/faqs/listing")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count_suffix"] == ""
    assert body["empty_title"] == ""
    assert body["empty_body"] == ""
    assert "is_active" not in body
    assert "টি প্রশ্ন" not in response.text
    assert "কোনো ফলাফল পাওয়া যায়নি" not in response.text


async def test_faq_listing_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/faqs/listing")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "faq-listing-viewer@implesia.com",
            "full_name": "FAQ Listing Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "faq-listing-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/faqs/listing",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_faq_listing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.patch(
        "/api/v1/admin/pages/faqs/listing",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["count_suffix"] == " questions"
    assert saved.json()["empty_title"] == "No matches"

    public = await client.get("/api/v1/pages/faqs/listing")
    assert public.json()["count_suffix"] == " questions"
    assert public.json()["empty_body"] == "Try another word."
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/faqs/listing",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/faqs/listing")
    assert cleared.json()["count_suffix"] == ""
    assert cleared.json()["empty_title"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/faqs/listing",
        headers=auth_headers,
        json=_body(),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/faqs/listing")
    assert shown.json()["empty_title"] == "No matches"
