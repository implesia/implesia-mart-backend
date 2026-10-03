from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    heading: str = "Refund process",
    title: str = "Send a request",
) -> dict:
    return {
        "is_active": active,
        "icon": "receipt_long",
        "nav_label": "Refund",
        "heading": heading,
        "note": "Cash on delivery refunds are arranged case by case.",
        "steps": [
            {
                "title": title,
                "body": "Share the order number and the reason.",
                "is_active": True,
            }
        ],
    }


async def test_public_shipping_refund_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/shipping/refund")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["note"] == ""
    assert body["steps"] == []
    assert "is_active" not in body
    assert "রিফান্ড প্রক্রিয়া" not in response.text
    assert "অনুরোধ জানান" not in response.text
    assert "প্রোডাক্ট ফেরত এলে আমাদের টিম" not in response.text
    assert "নগদ ফেরত কেসের ভিত্তিতে" not in response.text


async def test_shipping_refund_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/shipping/refund")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "shipping-refund-viewer@implesia.com",
            "full_name": "Shipping Refund Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shipping-refund-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/shipping/refund",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_keeps_refund_step_ids(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/shipping/refund",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    missing = await client.patch(
        "/api/v1/admin/pages/shipping/refund",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["message"] == "Every step needs a title."

    saved = await client.patch(
        "/api/v1/admin/pages/shipping/refund",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    step_id = saved.json()["steps"][0]["id"]
    assert saved.json()["heading"] == "Refund process"
    assert saved.json()["note"].startswith("Cash on delivery")

    public = await client.get("/api/v1/pages/shipping/refund")
    assert public.json()["heading"] == "Refund process"
    assert public.json()["steps"][0]["title"] == "Send a request"
    assert "is_active" not in public.json()
    assert "is_active" not in public.json()["steps"][0]

    kept = await client.patch(
        "/api/v1/admin/pages/shipping/refund",
        headers=auth_headers,
        json={
            **_body(),
            "steps": [{**saved.json()["steps"][0], "title": "Request a refund"}],
        },
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["steps"][0]["id"] == step_id
    assert kept.json()["steps"][0]["title"] == "Request a refund"

    hidden = await client.patch(
        "/api/v1/admin/pages/shipping/refund",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/shipping/refund")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["steps"] == []
    assert cleared.json()["note"] == ""
