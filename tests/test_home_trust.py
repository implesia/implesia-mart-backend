from httpx import AsyncClient


async def test_public_trust_seeds_the_home_strip(client: AsyncClient) -> None:
    response = await client.get("/api/v1/home/trust")
    assert response.status_code == 200, response.text
    labels = [item["label"] for item in response.json()["items"]]
    assert labels == ["ক্যাশ অন ডেলিভারি", "সারাদেশে ডেলিভারি", "৩ দিন ইজি রিটার্ন"]
    assert response.json()["items"][0]["href"] == "/shipping-returns"
    assert response.json()["items"][0]["icon"] == "payments"


async def test_trust_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/trust")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "trust-viewer@implesia.com",
            "full_name": "Trust Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "trust-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/home/trust",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"label": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_manage_trust_benefits(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    listed = await client.get("/api/v1/admin/home/trust", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    original = [item["id"] for item in listed.json()]
    assert len(original) == 3

    created = await client.post(
        "/api/v1/admin/home/trust",
        headers=auth_headers,
        json={"icon": "verified", "label": "  Checked stock  ", "href": ""},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["label"] == "Checked stock"
    assert body["href"] == "/shipping-returns"
    assert body["is_active"] is True
    item_id = body["id"]

    hidden = await client.patch(
        f"/api/v1/admin/home/trust/{item_id}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert hidden.status_code == 200, hidden.text
    public = await client.get("/api/v1/home/trust")
    assert item_id not in {item["id"] for item in public.json()["items"]}

    order = [item_id, *original]
    moved = await client.put(
        "/api/v1/admin/home/trust/order",
        headers=auth_headers,
        json={"ids": order},
    )
    assert moved.status_code == 200, moved.text
    assert [item["id"] for item in moved.json()] == order

    incomplete = await client.put(
        "/api/v1/admin/home/trust/order",
        headers=auth_headers,
        json={"ids": original},
    )
    assert incomplete.status_code == 422

    blank = await client.post(
        "/api/v1/admin/home/trust",
        headers=auth_headers,
        json={"label": "   "},
    )
    assert blank.status_code == 422

    removed = await client.delete(f"/api/v1/admin/home/trust/{item_id}", headers=auth_headers)
    assert removed.status_code == 200
    again = await client.get("/api/v1/admin/home/trust", headers=auth_headers)
    assert [item["id"] for item in again.json()] == original
