from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    heading: str = "Shipping details",
    card: str = "Nationwide",
) -> dict:
    return {
        "is_active": active,
        "icon": "local_shipping",
        "nav_label": "Shipping",
        "heading": heading,
        "intro": "Stocked orders leave quickly.",
        "timelines_title": "Delivery times",
        "cards": [
            {
                "icon": "public",
                "eyebrow": "Coverage",
                "title": card,
                "body": "We deliver across the country.",
                "variant": "primary",
                "is_active": True,
            }
        ],
        "timelines": [{"label": "Inside Dhaka", "value": "24 to 48 hours", "is_active": True}],
        "notes": [
            {
                "icon": "bolt",
                "title": "Fast processing",
                "body": "Stocked orders are packed after confirmation.",
                "is_active": True,
            }
        ],
    }


async def test_public_shipping_block_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/shipping/shipping")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == ""
    assert body["cards"] == []
    assert body["timelines"] == []
    assert body["notes"] == []
    assert "is_active" not in body
    assert "শিপিং তথ্য" not in response.text
    assert "সারাদেশে ডেলিভারি" not in response.text
    assert "ডেলিভারি সময়সূচি" not in response.text
    assert "দ্রুত প্রসেসিং" not in response.text


async def test_shipping_block_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/shipping/shipping")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "shipping-block-viewer@implesia.com",
            "full_name": "Shipping Block Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shipping-block-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/shipping/shipping",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_keeps_shipping_item_ids(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/shipping/shipping",
        headers=auth_headers,
        json=_body(heading="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Heading is required."

    missing = await client.patch(
        "/api/v1/admin/pages/shipping/shipping",
        headers=auth_headers,
        json=_body(card="   "),
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["message"] == (
        "Fill in every card, time, and note, or remove the empty ones."
    )

    saved = await client.patch(
        "/api/v1/admin/pages/shipping/shipping",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    card_id = saved.json()["cards"][0]["id"]
    assert saved.json()["heading"] == "Shipping details"
    assert saved.json()["cards"][0]["variant"] == "primary"

    public = await client.get("/api/v1/pages/shipping/shipping")
    assert public.json()["heading"] == "Shipping details"
    assert public.json()["timelines"][0]["label"] == "Inside Dhaka"
    assert public.json()["notes"][0]["title"] == "Fast processing"
    assert "is_active" not in public.json()
    assert "is_active" not in public.json()["cards"][0]

    kept = await client.patch(
        "/api/v1/admin/pages/shipping/shipping",
        headers=auth_headers,
        json={
            **_body(),
            "cards": [{**saved.json()["cards"][0], "title": "Nationwide delivery"}],
        },
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["cards"][0]["id"] == card_id
    assert kept.json()["cards"][0]["title"] == "Nationwide delivery"

    styled = await client.patch(
        "/api/v1/admin/pages/shipping/shipping",
        headers=auth_headers,
        json={
            **_body(),
            "cards": [{**_body()["cards"][0], "variant": "highlighted"}],
        },
    )
    assert styled.status_code == 422
    assert styled.json()["error"]["message"] == "Choose a card style."

    hidden = await client.patch(
        "/api/v1/admin/pages/shipping/shipping",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/shipping/shipping")
    assert cleared.json()["heading"] == ""
    assert cleared.json()["cards"] == []
