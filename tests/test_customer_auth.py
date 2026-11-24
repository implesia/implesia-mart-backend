import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem, OrderOrigin, OrderSource, OrderStatus

_REGISTER_URL = "/api/v1/customer/auth/register"
_LOGIN_URL = "/api/v1/customer/auth/login"
_REFRESH_URL = "/api/v1/customer/auth/refresh"
_LOGOUT_URL = "/api/v1/customer/auth/logout"
_PROFILE_URL = "/api/v1/customer/profile"
_PASSWORD_URL = "/api/v1/customer/change-password"
_ORDERS_URL = "/api/v1/customer/orders"
_DASHBOARD_URL = "/api/v1/customer/dashboard-summary"


async def test_customer_register_and_login_phone(client: AsyncClient) -> None:
    # 1. Register with BD phone number
    reg_payload = {
        "full_name": "Tushar Customer",
        "phone": "+880 1711-223344",
        "password": "customer-password-123",
    }
    reg_resp = await client.post(_REGISTER_URL, json=reg_payload)
    assert reg_resp.status_code == 201
    tokens = reg_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"

    # 2. Login with normalized phone
    login_resp = await client.post(
        _LOGIN_URL,
        json={"identifier": "01711223344", "password": "customer-password-123"},
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    # 3. Login with formatted phone
    login_resp_fmt = await client.post(
        _LOGIN_URL,
        json={"identifier": "+8801711223344", "password": "customer-password-123"},
    )
    assert login_resp_fmt.status_code == 200


async def test_customer_register_with_email_and_login(client: AsyncClient) -> None:
    # Register with email and phone
    payload = {
        "full_name": "Rahim Khan",
        "phone": "01812345678",
        "email": "rahim.khan@example.com",
        "password": "rahim-password-secure",
    }
    reg_resp = await client.post(_REGISTER_URL, json=payload)
    assert reg_resp.status_code == 201

    # Login with email
    email_login = await client.post(
        _LOGIN_URL,
        json={"identifier": "rahim.khan@example.com", "password": "rahim-password-secure"},
    )
    assert email_login.status_code == 200

    # Login with phone
    phone_login = await client.post(
        _LOGIN_URL,
        json={"identifier": "01812345678", "password": "rahim-password-secure"},
    )
    assert phone_login.status_code == 200


async def test_customer_register_phone_validation(client: AsyncClient) -> None:
    # Invalid prefix 012
    res1 = await client.post(
        _REGISTER_URL,
        json={
            "full_name": "Invalid",
            "phone": "01234567890",
            "password": "valid-password",
        },
    )
    assert res1.status_code == 422

    # Too short
    res2 = await client.post(
        _REGISTER_URL,
        json={
            "full_name": "Invalid",
            "phone": "0171234567",
            "password": "valid-password",
        },
    )
    assert res2.status_code == 422


async def test_customer_duplicate_registration_conflict(client: AsyncClient) -> None:
    payload = {
        "full_name": "First User",
        "phone": "01911223344",
        "email": "first@example.com",
        "password": "password123",
    }
    res = await client.post(_REGISTER_URL, json=payload)
    assert res.status_code == 201

    # Duplicate phone
    res_dup_phone = await client.post(
        _REGISTER_URL,
        json={
            "full_name": "Second User",
            "phone": "01911223344",
            "password": "password456",
        },
    )
    assert res_dup_phone.status_code == 409

    # Duplicate email
    res_dup_email = await client.post(
        _REGISTER_URL,
        json={
            "full_name": "Third User",
            "phone": "01999887766",
            "email": "first@example.com",
            "password": "password456",
        },
    )
    assert res_dup_email.status_code == 409


async def test_customer_profile_read_and_update(client: AsyncClient) -> None:
    reg_resp = await client.post(
        _REGISTER_URL,
        json={
            "full_name": "Profile Tester",
            "phone": "01611223344",
            "password": "password123",
        },
    )
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Read profile
    prof_resp = await client.get(_PROFILE_URL, headers=headers)
    assert prof_resp.status_code == 200
    prof = prof_resp.json()
    assert prof["full_name"] == "Profile Tester"
    assert prof["phone"] == "01611223344"
    assert prof["district"] is None

    # Update profile
    update_payload = {
        "full_name": "Updated Name",
        "district": "Dhaka",
        "area": "Mirpur-10",
        "address": "House 12, Road 4",
    }
    patch_resp = await client.patch(_PROFILE_URL, json=update_payload, headers=headers)
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["full_name"] == "Updated Name"
    assert updated["district"] == "Dhaka"
    assert updated["area"] == "Mirpur-10"
    assert updated["address"] == "House 12, Road 4"


async def test_customer_change_password_and_sessions(client: AsyncClient) -> None:
    reg_resp = await client.post(
        _REGISTER_URL,
        json={
            "full_name": "Password User",
            "phone": "01511223344",
            "password": "old-password-123",
        },
    )
    token = reg_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Wrong current password fails
    fail_res = await client.post(
        _PASSWORD_URL,
        json={"current_password": "wrong-pw", "new_password": "new-password-456"},
        headers=headers,
    )
    assert fail_res.status_code == 401

    # Change password
    change_res = await client.post(
        _PASSWORD_URL,
        json={"current_password": "old-password-123", "new_password": "new-password-456"},
        headers=headers,
    )
    assert change_res.status_code == 200

    # Old password no longer works
    old_login = await client.post(
        _LOGIN_URL,
        json={"identifier": "01511223344", "password": "old-password-123"},
    )
    assert old_login.status_code == 401

    # New password works
    new_login = await client.post(
        _LOGIN_URL,
        json={"identifier": "01511223344", "password": "new-password-456"},
    )
    assert new_login.status_code == 200


async def test_customer_order_query_security_and_dashboard(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # 1. Register Customer A
    res_a = await client.post(
        _REGISTER_URL,
        json={"full_name": "Customer A", "phone": "01710000001", "password": "password123"},
    )
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 2. Register Customer B
    res_b = await client.post(
        _REGISTER_URL,
        json={"full_name": "Customer B", "phone": "01710000002", "password": "password123"},
    )
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Get User A and User B from db
    prof_a = (await client.get(_PROFILE_URL, headers=headers_a)).json()
    prof_b = (await client.get(_PROFILE_URL, headers=headers_b)).json()
    user_a_id = uuid.UUID(prof_a["id"])
    user_b_id = uuid.UUID(prof_b["id"])

    # Create 2 orders for Customer A (one new, one delivered)
    order_a1 = Order(
        number="ORD-A001",
        user_id=user_a_id,
        source=OrderSource.DIRECT.value,
        origin=OrderOrigin.ONLINE.value,
        status=OrderStatus.NEW.value,
        customer_name="Customer A",
        phone="01710000001",
        email="a@example.com",
        district="Dhaka",
        area="Dhanmondi",
        address="Road 27",
        delivery_zone="inside_dhaka",
        subtotal=1000,
        shipping=60,
        total=1060,
    )
    order_a1.items.append(
        OrderItem(
            title="Smart Kettle",
            slug="smart-kettle",
            unit_price=1000,
            quantity=1,
            line_total=1000,
            sku="SKU-KETTLE",
        )
    )

    order_a2 = Order(
        number="ORD-A002",
        user_id=user_a_id,
        source=OrderSource.DIRECT.value,
        origin=OrderOrigin.ONLINE.value,
        status=OrderStatus.DELIVERED.value,
        customer_name="Customer A",
        phone="01710000001",
        email="a@example.com",
        district="Dhaka",
        area="Dhanmondi",
        address="Road 27",
        delivery_zone="inside_dhaka",
        subtotal=2000,
        shipping=60,
        total=2060,
    )
    order_a2.items.append(
        OrderItem(
            title="Iron Machine",
            slug="iron-machine",
            unit_price=2000,
            quantity=1,
            line_total=2000,
            sku="SKU-IRON",
        )
    )

    # Create 1 order for Customer B
    order_b1 = Order(
        number="ORD-B001",
        user_id=user_b_id,
        source=OrderSource.DIRECT.value,
        origin=OrderOrigin.ONLINE.value,
        status=OrderStatus.CONFIRMED.value,
        customer_name="Customer B",
        phone="01710000002",
        email="b@example.com",
        district="Chittagong",
        area="GEC",
        address="Road 1",
        delivery_zone="outside_dhaka",
        subtotal=500,
        shipping=120,
        total=620,
    )

    db_session.add_all([order_a1, order_a2, order_b1])
    await db_session.commit()

    # 3. Customer A lists orders: should only see their 2 orders
    orders_resp_a = await client.get(_ORDERS_URL, headers=headers_a)
    assert orders_resp_a.status_code == 200
    orders_data_a = orders_resp_a.json()
    assert orders_data_a["total"] == 2
    order_numbers_a = [o["number"] for o in orders_data_a["items"]]
    assert "ORD-A001" in order_numbers_a
    assert "ORD-A002" in order_numbers_a
    assert "ORD-B001" not in order_numbers_a

    # 4. Customer B lists orders: should only see their 1 order
    orders_resp_b = await client.get(_ORDERS_URL, headers=headers_b)
    assert orders_resp_b.status_code == 200
    orders_data_b = orders_resp_b.json()
    assert orders_data_b["total"] == 1
    assert orders_data_b["items"][0]["number"] == "ORD-B001"

    # 5. Customer A fetches own order detail: succeeds
    detail_res = await client.get(f"{_ORDERS_URL}/ORD-A001", headers=headers_a)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["number"] == "ORD-A001"
    assert len(detail["items"]) == 1
    assert detail["items"][0]["title"] == "Smart Kettle"

    # 6. Customer A attempts to fetch Customer B's order: returns 404
    forbidden_res = await client.get(f"{_ORDERS_URL}/ORD-B001", headers=headers_a)
    assert forbidden_res.status_code == 404

    # 7. Customer Dashboard Summary for Customer A:
    # 2 total orders, 1 active order (ORD-A001 is NEW; ORD-A002 is DELIVERED),
    # total spent = 1060 + 2060 = 3120
    dash_res_a = await client.get(_DASHBOARD_URL, headers=headers_a)
    assert dash_res_a.status_code == 200
    dash_a = dash_res_a.json()
    assert dash_a["total_orders"] == 2
    assert dash_a["active_orders"] == 1
    assert dash_a["total_spent"] == 3120
    assert dash_a["customer_name"] == "Customer A"

    # 8. Customer cannot access staff admin routes (RBAC check)
    admin_res = await client.get("/api/v1/admin/dashboard", headers=headers_a)
    assert admin_res.status_code in (401, 403)
