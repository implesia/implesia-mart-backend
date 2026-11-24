"""Phase 11 tests: staff-only admin auth, refresh grace window, viewer RBAC, and user management."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token, hash_password
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.services import refresh_token_service
from tests.conftest import TEST_PASSWORD


@pytest.mark.asyncio
async def test_customer_cannot_login_or_refresh_admin_auth_or_hit_admin_routes(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    customer = User(
        email="shopper@example.com",
        phone="01711002233",
        full_name="Store Shopper",
        password_hash=hash_password("shopper-passphrase"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)

    # 1. Customer cannot sign in via admin login endpoint
    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "shopper@example.com", "password": "shopper-passphrase"},
    )
    assert admin_login.status_code == 403
    assert "staff" in admin_login.json()["error"]["message"].lower()

    # 2. Customer CAN sign in via storefront customer login
    cust_login = await client.post(
        "/api/v1/customer/auth/login",
        json={"identifier": "shopper@example.com", "password": "shopper-passphrase"},
    )
    assert cust_login.status_code == 200, cust_login.text
    cust_tokens = cust_login.json()
    cust_headers = {"Authorization": f"Bearer {cust_tokens['access_token']}"}

    # 3. Customer token is rejected by every admin read route
    for path in (
        "/api/v1/admin/coupons",
        "/api/v1/admin/delivery",
        "/api/v1/admin/pricing",
        "/api/v1/admin/inventory/suppliers",
        "/api/v1/admin/orders/new",
        "/api/v1/admin/reports/sales",
        "/api/v1/users",
    ):
        resp = await client.get(path, headers=cust_headers)
        assert resp.status_code == 403, (
            f"Expected 403 for customer on {path}, got {resp.status_code}"
        )

    # 4. Customer refresh token cannot be exchanged at /api/v1/auth/refresh
    admin_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": cust_tokens["refresh_token"]},
    )
    assert admin_refresh.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_refresh_within_grace_window_does_not_logout_admin(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_token: str,
) -> None:
    del superadmin_token
    refresh_token_service.clear_grace_cache()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    first_refresh = login.json()["refresh_token"]

    # First rotation succeeds
    r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert r1.status_code == 200, r1.text
    second_refresh = r1.json()["refresh_token"]

    # Second concurrent rotation with the same old token within 30s returns idempotently
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert r2.status_code == 200, r2.text
    assert r2.json()["refresh_token"] == second_refresh

    # And the successor token is STILL valid (family was not revoked!)
    r3 = await client.post("/api/v1/auth/refresh", json={"refresh_token": second_refresh})
    assert r3.status_code == 200, r3.text
    third_refresh = r3.json()["refresh_token"]

    # After logout, reusing even within 30s must fail with 401
    out = await client.post("/api/v1/auth/logout", json={"refresh_token": third_refresh})
    assert out.status_code == 200
    after_logout = await client.post("/api/v1/auth/refresh", json={"refresh_token": second_refresh})
    assert after_logout.status_code == 401

    # Also verify cross-worker fallback (cache miss within grace window)
    login2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    t1 = login2.json()["refresh_token"]
    rot = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1})
    assert rot.status_code == 200
    refresh_token_service.clear_grace_cache()
    rot_fallback = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1})
    assert rot_fallback.status_code == 200

    # Backdating beyond 30s revokes the family
    old_jti = decode_token(t1, "refresh")["jti"]
    row = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.jti_hash == refresh_token_service.hash_jti(old_jti))
    )
    assert row is not None
    row.revoked_at = datetime.now(UTC) - timedelta(seconds=45)
    await db_session.commit()
    refresh_token_service.clear_grace_cache()

    expired_reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1})
    assert expired_reuse.status_code == 401


@pytest.mark.asyncio
async def test_viewer_read_only_and_write_forbidden(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "viewer@implesia.com",
            "full_name": "Audit Viewer",
            "password": "viewer-passphrase-123",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@implesia.com", "password": "viewer-passphrase-123"},
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Viewer can read viewer-allowed endpoints
    assert (await client.get("/api/v1/admin/coupons", headers=viewer_headers)).status_code == 200
    assert (
        await client.get("/api/v1/admin/inventory/suppliers", headers=viewer_headers)
    ).status_code == 200
    assert (
        await client.get("/api/v1/admin/reports/sales?preset=today", headers=viewer_headers)
    ).status_code == 200

    # Viewer gets 403 on write endpoints and superadmin RBAC endpoints
    write_supplier = await client.post(
        "/api/v1/admin/inventory/suppliers",
        headers=viewer_headers,
        json={"name": "Blocked Supplier"},
    )
    assert write_supplier.status_code == 403

    write_coupon = await client.post(
        "/api/v1/admin/coupons",
        headers=viewer_headers,
        json={"code": "NOPE10", "discount_type": "percent", "discount_value": 10},
    )
    assert write_coupon.status_code == 403

    users_list = await client.get("/api/v1/users", headers=viewer_headers)
    assert users_list.status_code == 403


@pytest.mark.asyncio
async def test_role_downgrade_revokes_sessions_and_user_management_endpoints(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # Seed an editor and a customer
    editor_res = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "ops@implesia.com",
            "full_name": "Ops Editor",
            "password": "editor-passphrase-123",
            "role": "editor",
            "is_active": True,
        },
    )
    assert editor_res.status_code == 201
    editor_id = editor_res.json()["id"]

    customer = User(
        email=None,
        phone="01812345678",
        full_name="Phone Only Buyer",
        password_hash=hash_password("buyer-passphrase-123"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(customer)
    await db_session.commit()

    # Editor signs in
    ed_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "ops@implesia.com", "password": "editor-passphrase-123"},
    )
    assert ed_login.status_code == 200
    ed_tokens = ed_login.json()
    ed_headers = {"Authorization": f"Bearer {ed_tokens['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=ed_headers)).status_code == 200

    # Superadmin downgrades editor -> viewer
    downgrade = await client.patch(
        f"/api/v1/users/{editor_id}",
        headers=auth_headers,
        json={"role": "viewer"},
    )
    assert downgrade.status_code == 200, downgrade.text
    assert downgrade.json()["role"] == "viewer"

    # Editor's existing access AND refresh tokens are immediately revoked!
    assert (await client.get("/api/v1/auth/me", headers=ed_headers)).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": ed_tokens["refresh_token"]}
        )
    ).status_code == 401

    # Verify GET /api/v1/users filters & summary counts (including phone-only customer)
    all_users = await client.get("/api/v1/users", headers=auth_headers)
    assert all_users.status_code == 200, all_users.text
    body = all_users.json()
    assert body["summary"]["total_users"] >= 3
    assert body["summary"]["staff_count"] >= 2
    assert body["summary"]["customer_count"] >= 1
    assert body["summary"]["active_count"] >= 3

    staff_only = await client.get("/api/v1/users?role=staff", headers=auth_headers)
    assert staff_only.status_code == 200
    assert all(item["role"] != "customer" for item in staff_only.json()["items"])

    search_phone = await client.get("/api/v1/users?q=01812345678", headers=auth_headers)
    assert search_phone.status_code == 200
    assert len(search_phone.json()["items"]) == 1
    assert search_phone.json()["items"][0]["full_name"] == "Phone Only Buyer"

    # Verify GET /api/v1/users/roles-matrix
    matrix = await client.get("/api/v1/users/roles-matrix", headers=auth_headers)
    assert matrix.status_code == 200, matrix.text
    m_body = matrix.json()
    role_keys = [r["role"] for r in m_body["roles"]]
    assert role_keys == ["superadmin", "editor", "viewer", "customer"]
    assert len(m_body["modules"]) >= 6
