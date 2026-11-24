"""Phase 16 tests: Dynamic database-backed RBAC permissions matrix & live enforcement."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.audit_event import AuditAction, AuditEvent
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.services import permission_service


@pytest.fixture(autouse=True)
def _clear_permission_cache() -> None:
    permission_service.invalidate_permission_cache()
    yield  # type: ignore[misc]
    permission_service.invalidate_permission_cache()


async def _create_staff_headers(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    email: str,
    role: UserRole,
) -> dict[str, str]:
    password = "staff-passphrase-1234"
    user = User(
        email=email,
        full_name=f"{role.value.title()} User",
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_superadmin_can_update_and_reset_roles_matrix_and_locked_roles_protected(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    permission_service.invalidate_permission_cache()

    # 1. Read live dynamic matrix
    res = await client.get("/api/v1/users/roles-matrix", headers=auth_headers)
    assert res.status_code == 200, res.text
    matrix = res.json()
    module_keys = {item["key"] for item in matrix["module_definitions"]}
    assert "communication" in module_keys
    assert len(matrix["module_definitions"]) == 13
    by_role = {r["role"]: r for r in matrix["roles"]}
    assert by_role["superadmin"]["editable"] is False
    assert by_role["customer"]["editable"] is False
    assert by_role["editor"]["editable"] is True
    assert by_role["viewer"]["editable"] is True

    # 2. Locked roles (superadmin, customer) MUST reject updates with 403
    for locked_role in ("superadmin", "customer"):
        locked_res = await client.put(
            "/api/v1/users/roles-matrix",
            headers=auth_headers,
            json={
                "updates": [
                    {
                        "role": locked_role,
                        "module_key": "orders",
                        "access_level": "read_only",
                    }
                ]
            },
        )
        assert locked_res.status_code == 403, (locked_role, locked_res.text)

    # 3. Superadmin updates editor & viewer permissions
    update_res = await client.put(
        "/api/v1/users/roles-matrix",
        headers=auth_headers,
        json={
            "updates": [
                {"role": "viewer", "module_key": "orders", "access_level": "read_write"},
                {"role": "editor", "module_key": "reports", "access_level": "none"},
            ]
        },
    )
    assert update_res.status_code == 200, update_res.text
    updated_by_role = {r["role"]: r for r in update_res.json()["roles"]}
    viewer_orders = next(
        p for p in updated_by_role["viewer"]["permissions"] if p["module_key"] == "orders"
    )
    editor_reports = next(
        p for p in updated_by_role["editor"]["permissions"] if p["module_key"] == "reports"
    )
    assert viewer_orders["access"] == "read_write"
    assert editor_reports["access"] == "none"

    # Audit log recorded ROLE_PERMISSIONS_UPDATED
    audit_row = await db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == AuditAction.ROLE_PERMISSIONS_UPDATED)
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit_row is not None

    # 4. Reset restores defaults
    reset_res = await client.post("/api/v1/users/roles-matrix/reset", headers=auth_headers)
    assert reset_res.status_code == 200, reset_res.text
    reset_by_role = {r["role"]: r for r in reset_res.json()["roles"]}
    viewer_orders_reset = next(
        p for p in reset_by_role["viewer"]["permissions"] if p["module_key"] == "orders"
    )
    editor_reports_reset = next(
        p for p in reset_by_role["editor"]["permissions"] if p["module_key"] == "reports"
    )
    assert viewer_orders_reset["access"] == "read_only"
    assert editor_reports_reset["access"] == "read_only"


@pytest.mark.asyncio
async def test_live_api_enforcement_and_auth_me_permissions(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    permission_service.invalidate_permission_cache()

    viewer_headers = await _create_staff_headers(
        client, db_session, email="dyn-viewer@implesia.com", role=UserRole.VIEWER
    )
    editor_headers = await _create_staff_headers(
        client, db_session, email="dyn-editor@implesia.com", role=UserRole.EDITOR
    )

    # Create a test order so we can test PATCH /api/v1/admin/orders/{id}
    order = Order(
        number="IM-RBAC-1001",
        source="cart",
        status=OrderStatus.NEW,
        customer_name="Test Buyer",
        phone="01711112222",
        district="Dhaka",
        area="Dhanmondi",
        address="House 10",
        delivery_zone="inside",
        payment_method="cod",
        subtotal=1000,
        shipping=60,
        total=1060,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    order_id = str(order.id)

    # Default state:
    # - Viewer CANNOT write orders (403)
    # - Editor CAN read reports (200)
    assert (
        await client.patch(
            f"/api/v1/admin/orders/{order_id}",
            headers=viewer_headers,
            json={"notes": "Viewer attempt before grant"},
        )
    ).status_code == 403
    assert (
        await client.get("/api/v1/admin/reports/sales?preset=today", headers=editor_headers)
    ).status_code == 200

    # /api/v1/auth/me returns live permissions map
    me_viewer_before = await client.get("/api/v1/auth/me", headers=viewer_headers)
    assert me_viewer_before.status_code == 200
    assert me_viewer_before.json()["permissions"]["orders"] == "read_only"

    me_superadmin = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me_superadmin.status_code == 200
    assert me_superadmin.json()["permissions"]["rbac"] == "full"
    assert me_superadmin.json()["permissions"]["audit_deletes"] == "full"

    # Superadmin grants viewer -> orders = read_write AND revokes editor -> reports = none
    upd = await client.put(
        "/api/v1/users/roles-matrix",
        headers=auth_headers,
        json={
            "updates": [
                {"role": "viewer", "module_key": "orders", "access_level": "read_write"},
                {"role": "editor", "module_key": "reports", "access_level": "none"},
            ]
        },
    )
    assert upd.status_code == 200, upd.text

    # Immediately enforced (cache invalidated):
    # 1. Viewer CAN now update orders
    patch_ok = await client.patch(
        f"/api/v1/admin/orders/{order_id}",
        headers=viewer_headers,
        json={"notes": "Viewer updated after grant"},
    )
    assert patch_ok.status_code == 200, patch_ok.text
    assert patch_ok.json()["notes"] == "Viewer updated after grant"

    # 2. Editor is NOW blocked from /api/v1/admin/reports/* with 403
    report_blocked = await client.get(
        "/api/v1/admin/reports/sales?preset=today",
        headers=editor_headers,
    )
    assert report_blocked.status_code == 403

    # 3. /api/v1/auth/me reflects the updated permissions immediately
    me_viewer_after = await client.get("/api/v1/auth/me", headers=viewer_headers)
    assert me_viewer_after.json()["permissions"]["orders"] == "read_write"

    me_editor_after = await client.get("/api/v1/auth/me", headers=editor_headers)
    assert me_editor_after.json()["permissions"]["reports"] == "none"

    # Cleanup: reset defaults so other tests are unaffected
    await client.post("/api/v1/users/roles-matrix/reset", headers=auth_headers)
    permission_service.invalidate_permission_cache()
