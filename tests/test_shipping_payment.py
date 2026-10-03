from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    heading: str = "Payment methods",
    title: str = "Cash on delivery",
) -> dict:
    return {
        "is_active": active,
        "icon": "payments",
        "nav_label": "Payment",
        "heading": heading,
        "intro": "Pay when the order arrives.",
        "cards": [
            {
                "icon": "handshake",
                "badge": "Popular",
                "title": title,
                "body": "Check the product, then pay.",
                "footnote": "Pay after you receive it",
                "is_active": True,
            }
        ],
    }


async def test_public_shipping_payment_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/shipping/payment")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["intro"] == ""
    assert body["cards"] == []
    assert "is_active" not in body
    assert "পেমেন্ট পদ্ধতি" not in response.text
    assert "পেমেন্ট সহজ ও স্বচ্ছ" not in response.text
    assert "ক্যাশ অন ডেলিভারি" not in response.text
    assert "মোবাইল ব্যাংকিং" not in response.text
    assert "হাতে পেয়ে টাকা দেওয়া যায়" not in response.text


async def test_shipping_payment_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/shipping/payment")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "shipping-payment-viewer@implesia.com",
            "full_name": "Shipping Payment Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shipping-payment-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/shipping/payment",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_keeps_payment_card_ids(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/shipping/payment",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    missing = await client.patch(
        "/api/v1/admin/pages/shipping/payment",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["message"] == "Every card needs a title."

    saved = await client.patch(
        "/api/v1/admin/pages/shipping/payment",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    card_id = saved.json()["cards"][0]["id"]
    assert saved.json()["heading"] == "Payment methods"

    public = await client.get("/api/v1/pages/shipping/payment")
    assert public.json()["heading"] == "Payment methods"
    assert public.json()["cards"][0]["title"] == "Cash on delivery"
    assert public.json()["cards"][0]["footnote"] == "Pay after you receive it"
    assert "is_active" not in public.json()
    assert "is_active" not in public.json()["cards"][0]

    kept = await client.patch(
        "/api/v1/admin/pages/shipping/payment",
        headers=auth_headers,
        json={
            **_body(),
            "cards": [{**saved.json()["cards"][0], "title": "Cash on delivery"}],
        },
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["cards"][0]["id"] == card_id

    hidden = await client.patch(
        "/api/v1/admin/pages/shipping/payment",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/shipping/payment")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["cards"] == []
