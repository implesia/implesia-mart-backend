import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import audit_service
from tests.conftest import TEST_PASSWORD
from tests.test_products import _create, _parts

NEW_PASSWORD = "replacement-passphrase"
FORBIDDEN = (
    NEW_PASSWORD,
    "plain-password-value",
    "vault-secret-value",
    "headerpayload.payloadpart.signaturepart",
)


async def _events(
    client: AsyncClient,
    headers: dict[str, str],
    **params: object,
) -> list[dict]:
    response = await client.get("/api/v1/admin/audit-events", headers=headers, params=params)
    assert response.status_code == 200, response.text
    for secret in FORBIDDEN:
        assert secret not in response.text
    return response.json()["items"]


async def test_price_and_stock_changes_are_recorded(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    created = await _create(client, auth_headers, title="Audit gown")

    renamed = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"title": "Renamed gown"}),
    )
    assert renamed.status_code == 200, renamed.text
    assert await _events(client, auth_headers, target_id=created["id"]) == []

    rejected = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"compare_at_price": 100}),
    )
    assert rejected.status_code == 422
    assert await _events(client, auth_headers, target_id=created["id"]) == []

    patched = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({"price": 18000, "quantity": 2, "status": "sold-out"}),
    )
    assert patched.status_code == 200, patched.text

    rows = await _events(client, auth_headers, target_id=created["id"])
    by_action = {row["action"]: row for row in rows}
    assert set(by_action) == {"PRODUCT_PRICE_UPDATED", "PRODUCT_STOCK_UPDATED"}
    price = by_action["PRODUCT_PRICE_UPDATED"]
    assert price["actor_user_id"] == me.json()["id"]
    assert price["target_type"] == "product"
    assert price["metadata"] == {"price": {"from": 15000, "to": 18000}}
    assert price["created_at"]
    stock = by_action["PRODUCT_STOCK_UPDATED"]
    assert stock["metadata"]["quantity"] == {"from": None, "to": 2}
    assert stock["metadata"]["status"] == {"from": "available", "to": "sold-out"}

    only_price = await _events(
        client, auth_headers, target_id=created["id"], action="PRODUCT_PRICE_UPDATED"
    )
    assert [row["action"] for row in only_price] == ["PRODUCT_PRICE_UPDATED"]


async def test_user_changes_are_recorded_without_secrets(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "staff@implesia.com",
            "full_name": "Staff",
            "password": "staff-passphrase",
            "role": "editor",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    renamed = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=auth_headers,
        json={"full_name": "Staff Two"},
    )
    assert renamed.status_code == 200, renamed.text
    assert await _events(client, auth_headers, target_id=user_id) == []

    updated = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=auth_headers,
        json={"role": "viewer", "is_active": False, "password": NEW_PASSWORD},
    )
    assert updated.status_code == 200, updated.text

    rows = await _events(client, auth_headers, target_id=user_id)
    by_action = {row["action"]: row for row in rows}
    assert set(by_action) == {"PASSWORD_CHANGED", "ROLE_CHANGED", "USER_DISABLED"}
    assert by_action["PASSWORD_CHANGED"]["actor_user_id"] == me.json()["id"]
    assert by_action["PASSWORD_CHANGED"]["metadata"] == {
        "via": "admin",
        "email": "staff@implesia.com",
    }
    assert by_action["ROLE_CHANGED"]["metadata"]["from"] == "editor"
    assert by_action["ROLE_CHANGED"]["metadata"]["to"] == "viewer"
    assert by_action["USER_DISABLED"]["target_type"] == "user"

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200, changed.text
    own = await _events(client, auth_headers, target_id=me.json()["id"], action="PASSWORD_CHANGED")
    assert own[0]["metadata"] == {"via": "self", "email": "admin@implesia.com"}
    assert NEW_PASSWORD not in str(own)


async def test_wrong_password_is_not_audited(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    rejected = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={"current_password": "wrong-password-entirely", "new_password": NEW_PASSWORD},
    )
    assert rejected.status_code == 401
    assert await _events(client, auth_headers, target_id=me.json()["id"]) == []


async def test_secrets_in_metadata_are_dropped(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    await audit_service.record(
        db_session,
        actor_id=uuid.UUID(me.json()["id"]),
        action="PASSWORD_CHANGED",
        target_type="user",
        target_id=me.json()["id"],
        metadata={
            "password": "plain-password-value",
            "access_token": "headerpayload.payloadpart.signaturepart",
            "refresh_token": "headerpayload.payloadpart.signaturepart",
            "secret": "vault-secret-value",
            "note": "headerpayload.payloadpart.signaturepart",
            "via": "self",
            "nested": {"password": "plain-password-value", "kept": "visible"},
        },
    )
    await db_session.commit()

    rows = await _events(client, auth_headers, target_id=me.json()["id"])
    assert rows[0]["metadata"] == {"via": "self", "nested": {"kept": "visible"}}


async def test_audit_log_is_superadmin_only(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/audit-events")
    assert anonymous.status_code == 401

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
    assert login.status_code == 200, login.text
    editor = await client.get(
        "/api/v1/admin/audit-events",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert editor.status_code == 403
