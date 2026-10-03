from httpx import AsyncClient

from tests.test_orders import SHIPPING, _key
from tests.test_products import _create


async def test_dashboard_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/dashboard")
    assert anonymous.status_code == 401

    allowed = await client.get("/api/v1/admin/dashboard", headers=auth_headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["orders"]["value"] == 0

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "viewer@implesia.com",
            "full_name": "Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.get(
        "/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403


async def test_editor_can_read_the_dashboard(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "editor@implesia.com",
            "full_name": "Editor",
            "password": "editor-passphrase",
            "role": "editor",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "editor@implesia.com", "password": "editor-passphrase"},
    )
    response = await client.get(
        "/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["range"] == "7d"
    assert body["grain"] == "day"
    assert len(body["statuses"]) == 6


async def test_overview_counts_sales_and_skips_cancelled(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    gown = await _create(client, auth_headers, title="Dash gown", price=500, quantity=4)
    lamp = await _create(
        client, auth_headers, title="Dash lamp", price=200, quantity=4, category="gadgets"
    )
    kept = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": gown["id"], "quantity": 2}],
            **SHIPPING,
            "district": "ঢাকা",
            "area": "ধানমন্ডি",
            "phone": "01711111111",
        },
    )
    assert kept.status_code == 201, kept.text
    dropped = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": lamp["id"], "quantity": 1}],
            **SHIPPING,
            "district": "চট্টগ্রাম",
            "phone": "01711111111",
            "customer_name": "Same Phone",
        },
    )
    assert dropped.status_code == 201, dropped.text
    cancelled = await client.patch(
        f"/api/v1/admin/orders/{dropped.json()['id']}",
        headers=auth_headers,
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text

    overview = await client.get("/api/v1/admin/dashboard?range=7d", headers=auth_headers)
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["orders"]["value"] == 2
    assert body["customers"]["value"] == 1
    assert body["revenue"]["value"] == kept.json()["total"]
    assert body["revenue"]["trend"]["direction"] == "new"
    assert body["pending"]["value"] == 1
    assert {row["number"] for row in body["recent"]} == {
        kept.json()["number"],
        dropped.json()["number"],
    }
    assert body["best_sellers"][0]["title"] == "Dash gown"
    assert body["best_sellers"][0]["units"] == 2
    assert body["areas"][0]["name"] == "Dhaka"
    assert body["categories"][0]["id"] == "fashion"
    assert body["order_count"] == 2


async def test_custom_range_needs_both_dates(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    missing = await client.get("/api/v1/admin/dashboard?range=custom", headers=auth_headers)
    assert missing.status_code == 422

    wide = await client.get(
        "/api/v1/admin/dashboard?range=custom&from=2020-01-01&to=2026-10-03",
        headers=auth_headers,
    )
    assert wide.status_code == 422
