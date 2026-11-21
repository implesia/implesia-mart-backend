"""Phase 17 tests: Dynamic Custom Roles CRUD, live enforcement, and safe deletion."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditAction, AuditEvent
from app.models.order import Order, OrderStatus
from app.services import permission_service


@pytest.mark.asyncio
async def test_custom_role_crud_live_enforcement_and_safe_delete(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # (a) Create a custom role with blank defaults AND another cloning from viewer
    create_blank = await client.post(
        "/api/v1/users/roles",
        headers=auth_headers,
        json={
            "label": "Order Manager",
            "description": "Manages daily orders and fulfillment only.",
        },
    )
    assert create_blank.status_code == 201, create_blank.text
    order_mgr = create_blank.json()
    assert order_mgr["slug"] == "order_manager"
    assert order_mgr["is_system"] is False
    assert order_mgr["admin_access"] is True

    create_cloned = await client.post(
        "/api/v1/users/roles",
        headers=auth_headers,
        json={
            "label": "Accountant",
            "clone_from_role": "viewer",
            "description": "Financial reporting and auditing.",
        },
    )
    assert create_cloned.status_code == 201, create_cloned.text
    assert create_cloned.json()["slug"] == "accountant"

    # Matrix includes both custom roles + system roles
    matrix_res = await client.get("/api/v1/users/roles-matrix", headers=auth_headers)
    assert matrix_res.status_code == 200
    by_role = {r["role"]: r for r in matrix_res.json()["roles"]}
    assert "order_manager" in by_role
    assert "accountant" in by_role
    # Blank role starts with all 'none'; cloned role inherited viewer's 'read_only' on reports
    om_orders = next(
        p for p in by_role["order_manager"]["permissions"] if p["module_key"] == "orders"
    )
    acc_reports = next(
        p for p in by_role["accountant"]["permissions"] if p["module_key"] == "reports"
    )
    assert om_orders["access"] == "none"
    assert acc_reports["access"] == "read_only"

    # Update custom role metadata
    upd_meta = await client.patch(
        "/api/v1/users/roles/order_manager",
        headers=auth_headers,
        json={"label": "Orders Lead", "description": "Updated description"},
    )
    assert upd_meta.status_code == 200, upd_meta.text
    assert upd_meta.json()["label"] == "Orders Lead"

    # (b) Assign custom role to a staff user and verify login + enforcement
    user_res = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "orders.lead@implesia.com",
            "full_name": "Orders Lead Staff",
            "password": "orders-lead-passphrase-123",
            "role": "order_manager",
            "is_active": True,
        },
    )
    assert user_res.status_code == 201, user_res.text
    staff_id = user_res.json()["id"]

    # Filter /api/v1/users?role=order_manager and ?role=staff
    filtered = await client.get("/api/v1/users?role=order_manager", headers=auth_headers)
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == staff_id

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "orders.lead@implesia.com", "password": "orders-lead-passphrase-123"},
    )
    assert login.status_code == 200, login.text
    staff_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    staff_refresh = login.json()["refresh_token"]

    me_res = await client.get("/api/v1/auth/me", headers=staff_headers)
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "order_manager"
    assert me_res.json()["admin_access"] is True
    assert me_res.json()["permissions"]["orders"] == "none"

    # Refresh token works for custom staff role
    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": staff_refresh})
    assert refreshed.status_code == 200, refreshed.text
    staff_headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}

    # Create a sample order
    order = Order(
        number="IM-ROLE-2001",
        source="cart",
        status=OrderStatus.NEW,
        customer_name="Role Test Buyer",
        phone="01711113333",
        district="Dhaka",
        area="Banani",
        address="Road 11",
        delivery_zone="inside",
        payment_method="cod",
        subtotal=1200,
        shipping=60,
        total=1260,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    order_id = str(order.id)

    # Currently order_manager has orders=none -> 403 on orders & reports
    assert (
        await client.get("/api/v1/admin/orders/overview", headers=staff_headers)
    ).status_code == 403
    assert (
        await client.get("/api/v1/admin/reports/sales?preset=today", headers=staff_headers)
    ).status_code == 403

    # (c) Dynamically grant order_manager -> orders=read_write
    grant = await client.put(
        "/api/v1/users/roles-matrix",
        headers=auth_headers,
        json={
            "updates": [
                {"role": "order_manager", "module_key": "orders", "access_level": "read_write"}
            ]
        },
    )
    assert grant.status_code == 200, grant.text

    # Immediately allowed on orders read & write, still blocked on reports
    assert (
        await client.get("/api/v1/admin/orders/overview", headers=staff_headers)
    ).status_code == 200
    patch_order = await client.patch(
        f"/api/v1/admin/orders/{order_id}",
        headers=staff_headers,
        json={"notes": "Handled by Order Manager"},
    )
    assert patch_order.status_code == 200, patch_order.text
    assert patch_order.json()["notes"] == "Handled by Order Manager"
    assert (
        await client.get("/api/v1/admin/reports/sales?preset=today", headers=staff_headers)
    ).status_code == 403

    # (d) System roles CANNOT be deleted
    for sys_role in ("superadmin", "editor", "viewer", "customer"):
        del_sys = await client.delete(f"/api/v1/users/roles/{sys_role}", headers=auth_headers)
        assert del_sys.status_code == 403, (sys_role, del_sys.text)

    # (e) Safe-delete custom role with assigned users
    impact_res = await client.get(
        "/api/v1/users/roles/order_manager/delete-impact", headers=auth_headers
    )
    assert impact_res.status_code == 200
    impact = impact_res.json()
    assert impact["can_delete"] is True
    assert impact["assigned_users_count"] == 1

    # Deleting without reassign_to_role fails (422)
    del_no_reassign = await client.delete("/api/v1/users/roles/order_manager", headers=auth_headers)
    assert del_no_reassign.status_code == 422

    # Deleting WITH reassign_to_role=viewer reassigns user, revokes sessions, deletes role
    del_ok = await client.delete(
        "/api/v1/users/roles/order_manager?reassign_to_role=viewer",
        headers=auth_headers,
    )
    assert del_ok.status_code == 204, del_ok.text

    # Old session of reassigned user is immediately revoked (401)
    revoked_check = await client.get("/api/v1/auth/me", headers=staff_headers)
    assert revoked_check.status_code == 401

    # User is now 'viewer'
    reassigned_user = await client.get(f"/api/v1/users/{staff_id}", headers=auth_headers)
    assert reassigned_user.status_code == 200
    assert reassigned_user.json()["role"] == "viewer"

    # Audit events recorded
    created_evt = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.ROLE_CREATED,
            AuditEvent.target_id == "order_manager",
        )
    )
    deleted_evt = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.ROLE_DELETED,
            AuditEvent.target_id == "order_manager",
        )
    )
    assert created_evt is not None
    assert deleted_evt is not None
    permission_service.invalidate_permission_cache()
