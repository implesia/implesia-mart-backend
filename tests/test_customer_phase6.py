import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.notification import CustomerNotification
from app.models.order import ActivityAction, Order, OrderActivity, OrderItem, OrderStatus
from app.models.product import Product, StockStatus
from app.models.user import User, UserRole
from app.services import notification_service, refresh_token_service


@pytest.mark.asyncio
async def test_notifications_flow(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db = db_session
    # 1. Create customer
    user = User(
        full_name="Notification Tester",
        phone="01711223399",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    tokens = await refresh_token_service.issue_session(db, user)
    headers = {"Authorization": f"Bearer {tokens.access_token}"}

    # 2. Create notification directly
    order = Order(
        number="IM-NOTIF01",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.CONFIRMED.value,
        payment_method="cod",
        customer_name=user.full_name,
        phone=user.phone,
        district="Dhaka",
        area="Mirpur",
        address="Test",
        delivery_zone="inside",
        subtotal=1000,
        shipping=60,
        total=1060,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    notif = await notification_service.create_order_status_notification(
        db, order, "confirmed", language="bn"
    )
    assert notif is not None
    assert notif.user_id == user.id
    assert notif.is_read is False

    # 3. Fetch notifications via API
    resp = await client.get("/api/v1/customer/notifications", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["unread_count"] >= 1
    assert data["items"][0]["id"] == str(notif.id)

    # 4. Mark single read
    patch_resp = await client.patch(
        f"/api/v1/customer/notifications/{notif.id}/read", headers=headers
    )
    assert patch_resp.status_code == 200

    # 5. Mark all read
    post_resp = await client.post(
        "/api/v1/customer/notifications/mark-all-read", headers=headers
    )
    assert post_resp.status_code == 200


@pytest.mark.asyncio
async def test_purchased_products_and_tracking(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db = db_session
    user = User(
        full_name="Tracking Tester",
        phone="01811223388",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    tokens = await refresh_token_service.issue_session(db, user)
    headers = {"Authorization": f"Bearer {tokens.access_token}"}

    product = Product(
        title="Tracking Test Product",
        slug=f"track-prod-{uuid.uuid4().hex[:6]}",
        price=1200,
        status=StockStatus.AVAILABLE.value,
        content={},
        published=True,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    order = Order(
        number="IM-TRACK01",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.SHIPPED.value,
        payment_method="cod",
        courier_name="Steadfast",
        tracking_number="ST-998877",
        customer_name=user.full_name,
        phone=user.phone,
        district="Dhaka",
        area="Mirpur",
        address="Test",
        delivery_zone="inside",
        subtotal=1200,
        shipping=60,
        total=1260,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    order_item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        title=product.title,
        slug=product.slug,
        unit_price=1200,
        quantity=1,
        line_total=1200,
        sku="TEST-SKU",
    )
    db.add(order_item)
    await db.commit()

    # 1. Purchased products list
    p_resp = await client.get("/api/v1/customer/purchased-products", headers=headers)
    assert p_resp.status_code == 200
    p_items = p_resp.json()
    assert len(p_items) == 1
    assert p_items[0]["product_id"] == str(product.id)
    assert p_items[0]["can_review"] is True

    # 2. Tracking details
    t_resp = await client.get(f"/api/v1/customer/orders/{order.number}/tracking", headers=headers)
    assert t_resp.status_code == 200
    t_data = t_resp.json()
    assert t_data["order_number"] == order.number
    assert t_data["courier_name"] == "Steadfast"
    assert len(t_data["timeline"]) == 5
    # Shipped is step index 3 -> steps 0, 1, 2, 3 should be completed
    assert t_data["timeline"][0]["completed"] is True
    assert t_data["timeline"][3]["completed"] is True
    assert t_data["timeline"][4]["completed"] is False


@pytest.mark.asyncio
async def test_product_reviews_flow(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db = db_session
    # 1. Customer who hasn't bought product
    user1 = User(
        full_name="Non Purchaser",
        phone="01911223377",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    # 2. Customer who bought product
    user2 = User(
        full_name="Verified Purchaser",
        phone="01611223366",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    product = Product(
        title="Reviewable Dress",
        slug=f"review-dress-{uuid.uuid4().hex[:6]}",
        price=2500,
        status=StockStatus.AVAILABLE.value,
        content={},
        published=True,
    )
    db.add_all([user1, user2, product])
    await db.commit()
    await db.refresh(user1)
    await db.refresh(user2)
    await db.refresh(product)
    product_id = product.id
    user2_name = user2.full_name

    order = Order(
        number="IM-REV01",
        user_id=user2.id,
        source="direct",
        channel="website",
        status=OrderStatus.DELIVERED.value,
        payment_method="cod",
        customer_name=user2.full_name,
        phone=user2.phone,
        district="Dhaka",
        area="Mirpur",
        address="Test",
        delivery_zone="inside",
        subtotal=2500,
        shipping=60,
        total=2560,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    order_item = OrderItem(
        order_id=order.id,
        product_id=product_id,
        title=product.title,
        slug=product.slug,
        unit_price=2500,
        quantity=1,
        line_total=2500,
        sku="REV-SKU",
    )
    db.add(order_item)
    await db.commit()

    tokens1 = await refresh_token_service.issue_session(db, user1)
    tokens2 = await refresh_token_service.issue_session(db, user2)

    # User 1 cannot review
    can_resp1 = await client.get(
        f"/api/v1/products/{product_id}/can-review",
        headers={"Authorization": f"Bearer {tokens1.access_token}"},
    )
    assert can_resp1.status_code == 200
    assert can_resp1.json()["can_review"] is False

    # User 2 can review
    can_resp2 = await client.get(
        f"/api/v1/products/{product_id}/can-review",
        headers={"Authorization": f"Bearer {tokens2.access_token}"},
    )
    assert can_resp2.status_code == 200
    assert can_resp2.json()["can_review"] is True

    # User 2 submits review
    review_payload = {
        "rating": 5,
        "headline": "অসাধারণ কোয়ালিটি!",
        "comment": "কাপড়ের মান খুবই ভালো এবং সময়মতো ডেলিভারি পেয়েছি।",
    }
    rev_post = await client.post(
        f"/api/v1/products/{product_id}/reviews",
        json=review_payload,
        headers={"Authorization": f"Bearer {tokens2.access_token}"},
    )
    assert rev_post.status_code == 201
    rev_data = rev_post.json()
    assert rev_data["rating"] == 5
    assert rev_data["user_name"] == user2_name
    assert rev_data["is_verified_purchase"] is True

    # User 2 tries to review again -> ConflictError (409)
    rev_post_again = await client.post(
        f"/api/v1/products/{product_id}/reviews",
        json=review_payload,
        headers={"Authorization": f"Bearer {tokens2.access_token}"},
    )
    assert rev_post_again.status_code == 409

    # Public review list & summary
    pub_list = await client.get(f"/api/v1/products/{product_id}/reviews")
    assert pub_list.status_code == 200
    pub_data = pub_list.json()
    assert pub_data["total"] == 1
    assert pub_data["summary"]["average_rating"] == 5.0
    assert pub_data["summary"]["total_reviews"] == 1
    assert pub_data["summary"]["rating_histogram"]["5"] == 1


@pytest.mark.asyncio
async def test_avatar_upload(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db = db_session
    user = User(
        full_name="Avatar Tester",
        phone="01511223355",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    tokens = await refresh_token_service.issue_session(db, user)
    headers = {"Authorization": f"Bearer {tokens.access_token}"}

    # 1x1 transparent PNG bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00"
        b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    files = {"file": ("avatar.png", io.BytesIO(png_bytes), "image/png")}
    resp = await client.post("/api/v1/customer/profile/avatar", files=files, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["avatar_url"] is not None
    assert "/media/avatars/" in data["avatar_url"]

    # Delete avatar removes URL and deletes local file
    avatar_name = data["avatar_url"].removeprefix("/media/avatars/")
    avatar_path = (settings.media_root / "avatars" / avatar_name).resolve()
    assert avatar_path.exists()

    del_resp = await client.delete("/api/v1/customer/profile/avatar", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["avatar_url"] is None
    assert not avatar_path.exists()


@pytest.mark.asyncio
async def test_profile_clearing_optional_fields(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = User(
        full_name="Clearable Customer",
        phone="01755667788",
        email="clear.me@example.com",
        district="Dhaka",
        area="Banani",
        address="Road 11, Block F",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    tokens = await refresh_token_service.issue_session(db_session, user)
    headers = {"Authorization": f"Bearer {tokens.access_token}"}

    # Clear email & district with empty strings, area & address with null
    resp = await client.patch(
        "/api/v1/customer/profile",
        json={
            "email": "",
            "district": "   ",
            "area": None,
            "address": None,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["full_name"] == "Clearable Customer"
    assert data["email"] is None
    assert data["district"] is None
    assert data["area"] is None
    assert data["address"] is None

    # Omitted fields stay untouched when updating only one field
    resp2 = await client.patch(
        "/api/v1/customer/profile",
        json={"district": "Sylhet"},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["district"] == "Sylhet"
    assert resp2.json()["email"] is None
    assert resp2.json()["area"] is None

    # Clear district explicitly with null
    resp3 = await client.patch(
        "/api/v1/customer/profile",
        json={"district": None},
        headers=headers,
    )
    assert resp3.status_code == 200
    assert resp3.json()["district"] is None


@pytest.mark.asyncio
async def test_dashboard_summary_extended_metrics(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = User(
        full_name="Summary Customer",
        phone="01855667788",
        email="summary@example.com",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    tokens = await refresh_token_service.issue_session(db_session, user)
    headers = {"Authorization": f"Bearer {tokens.access_token}"}

    orders = [
        Order(
            number="IM-SUM00001",
            user_id=user.id,
            source="direct",
            channel="website",
            status=OrderStatus.NEW.value,
            payment_method="cod",
            customer_name=user.full_name,
            phone=user.phone or "",
            district="Dhaka",
            area="Mirpur",
            address="Test 1",
            delivery_zone="inside",
            subtotal=1000,
            shipping=60,
            total=1060,
        ),
        Order(
            number="IM-SUM00002",
            user_id=user.id,
            source="direct",
            channel="website",
            status=OrderStatus.DELIVERED.value,
            payment_method="cod",
            customer_name=user.full_name,
            phone=user.phone or "",
            district="Dhaka",
            area="Mirpur",
            address="Test 2",
            delivery_zone="inside",
            subtotal=1500,
            shipping=60,
            total=1560,
        ),
        Order(
            number="IM-SUM00003",
            user_id=user.id,
            source="direct",
            channel="website",
            status=OrderStatus.CANCELLED.value,
            payment_method="cod",
            customer_name=user.full_name,
            phone=user.phone or "",
            district="Dhaka",
            area="Mirpur",
            address="Test 3",
            delivery_zone="inside",
            subtotal=2000,
            shipping=60,
            total=2060,
        ),
        Order(
            number="IM-SUM00004",
            user_id=user.id,
            source="direct",
            channel="website",
            status=OrderStatus.RETURNED.value,
            payment_method="cod",
            customer_name=user.full_name,
            phone=user.phone or "",
            district="Dhaka",
            area="Mirpur",
            address="Test 4",
            delivery_zone="inside",
            subtotal=3000,
            shipping=60,
            total=3060,
        ),
    ]
    orders[0].items.append(
        OrderItem(
            title="Item A", slug="item-a", unit_price=500, quantity=2, line_total=1000, sku="A"
        )
    )
    orders[1].items.append(
        OrderItem(
            title="Item B", slug="item-b", unit_price=500, quantity=3, line_total=1500, sku="B"
        )
    )
    orders[2].items.append(
        OrderItem(
            title="Item C", slug="item-c", unit_price=500, quantity=4, line_total=2000, sku="C"
        )
    )
    orders[3].items.append(
        OrderItem(
            title="Item D", slug="item-d", unit_price=600, quantity=5, line_total=3000, sku="D"
        )
    )
    db_session.add_all(orders)

    now = datetime.now(UTC)
    db_session.add_all(
        [
            CustomerNotification(
                user_id=user.id,
                type="order_status",
                title="Unread recent",
                message="Recent unread",
                is_read=False,
                created_at=now - timedelta(days=2),
            ),
            CustomerNotification(
                user_id=user.id,
                type="order_status",
                title="Read recent",
                message="Recent read",
                is_read=True,
                created_at=now - timedelta(days=1),
            ),
            CustomerNotification(
                user_id=user.id,
                type="order_status",
                title="Unread expired",
                message="Older than 30 days",
                is_read=False,
                created_at=now - timedelta(days=31),
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/customer/dashboard-summary", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_orders"] == 4
    assert data["active_orders"] == 1
    assert data["delivered_orders"] == 1
    assert data["cancelled_orders"] == 1
    assert data["total_products_purchased"] == 5  # 2 + 3; excludes cancelled/returned
    assert data["unread_notifications"] == 1  # excludes read and >30d expired
    assert data["total_spent"] == 2620  # 1060 + 1560


@pytest.mark.asyncio
async def test_notification_auto_purge_delete_and_triggers(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user = User(
        full_name="Notif Auto Customer",
        phone="01955667788",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    other_user = User(
        full_name="Other Customer",
        phone="01955667799",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    product = Product(
        title="Notif Trigger Dress",
        slug=f"notif-dress-{uuid.uuid4().hex[:6]}",
        price=1000,
        quantity=20,
        status=StockStatus.AVAILABLE.value,
        content={},
        published=True,
    )
    db_session.add_all([user, other_user, product])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(other_user)
    await db_session.refresh(product)

    tokens = await refresh_token_service.issue_session(db_session, user)
    cust_headers = {"Authorization": f"Bearer {tokens.access_token}"}

    # 1. Expired (>30d) notification is physically deleted on list
    now = datetime.now(UTC)
    expired_notif = CustomerNotification(
        user_id=user.id,
        type="order_status",
        title="Expired",
        message="Old message",
        is_read=False,
        created_at=now - timedelta(days=35),
    )
    other_expired = CustomerNotification(
        user_id=other_user.id,
        type="order_status",
        title="Other Expired",
        message="Other old message",
        is_read=False,
        created_at=now - timedelta(days=40),
    )
    other_fresh = CustomerNotification(
        user_id=other_user.id,
        type="order_status",
        title="Other Fresh",
        message="Other new message",
        is_read=False,
        created_at=now - timedelta(days=1),
    )
    db_session.add_all([expired_notif, other_expired, other_fresh])
    await db_session.commit()
    expired_id = expired_notif.id
    other_fresh_id = other_fresh.id

    # Reset throttle so global purge executes during list
    notification_service._last_purge_at = None
    list_resp = await client.get("/api/v1/customer/notifications", headers=cust_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["items"] == []

    # Verify physical deletion from database for both users
    remaining_expired = await db_session.scalar(
        select(CustomerNotification).where(CustomerNotification.id == expired_id)
    )
    assert remaining_expired is None
    remaining_other_expired = await db_session.scalar(
        select(CustomerNotification).where(CustomerNotification.id == other_expired.id)
    )
    assert remaining_other_expired is None

    # 2. Standalone purge helper works cleanly
    another_expired = CustomerNotification(
        user_id=user.id,
        type="order_status",
        title="Standalone Expired",
        message="Will be purged",
        is_read=False,
        created_at=now - timedelta(days=32),
    )
    db_session.add(another_expired)
    await db_session.commit()
    purged_count = await notification_service.purge_expired_notifications(db_session)
    assert purged_count == 1

    # 3. Order placement triggers 'new' notification for phone-matched customer;
    # idempotency replay must not duplicate it.
    order_payload = {
        "source": "direct",
        "items": [{"product_id": str(product.id), "quantity": 1}],
        "customer_name": "Notif Auto Customer",
        "phone": "01955667788",
        "district": "Dhaka",
        "area": "Mirpur",
        "address": "House 5, Road 7, Mirpur",
        "payment_method": "cod",
    }
    idem_key = f"notif-order-{uuid.uuid4().hex[:12]}"
    place_resp = await client.post(
        "/api/v1/orders",
        json=order_payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert place_resp.status_code == 201, place_resp.text
    order_id = place_resp.json()["id"]
    order_number = place_resp.json()["number"]

    # Replay same idempotency key should not duplicate notification
    replay_resp = await client.post(
        "/api/v1/orders",
        json=order_payload,
        headers={"Idempotency-Key": idem_key},
    )
    assert replay_resp.status_code == 201

    after_place = (await client.get("/api/v1/customer/notifications", headers=cust_headers)).json()
    assert len(after_place["items"]) == 1
    assert order_number in after_place["items"][0]["message"]
    new_notif_id = after_place["items"][0]["id"]

    # 4. Admin bulk-status update triggers notification automatically
    bulk_resp = await client.post(
        "/api/v1/admin/orders/bulk-status",
        json={"status": "confirmed", "ids": [order_id]},
        headers=auth_headers,
    )
    assert bulk_resp.status_code == 200, bulk_resp.text
    assert bulk_resp.json()["results"][0]["ok"] is True

    after_bulk = (await client.get("/api/v1/customer/notifications", headers=cust_headers)).json()
    assert len(after_bulk["items"]) == 2
    assert after_bulk["unread_count"] == 2

    # 5. Individual notification delete (owner succeeds, non-owner returns 404)
    del_other = await client.delete(
        f"/api/v1/customer/notifications/{other_fresh_id}", headers=cust_headers
    )
    assert del_other.status_code == 404

    del_own = await client.delete(
        f"/api/v1/customer/notifications/{new_notif_id}", headers=cust_headers
    )
    assert del_own.status_code == 200

    del_again = await client.delete(
        f"/api/v1/customer/notifications/{new_notif_id}", headers=cust_headers
    )
    assert del_again.status_code == 404

    after_del = (await client.get("/api/v1/customer/notifications", headers=cust_headers)).json()
    assert len(after_del["items"]) == 1


@pytest.mark.asyncio
async def test_order_tracking_activity_timestamps_and_terminal_statuses(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = User(
        full_name="Timeline Customer",
        phone="01766778899",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    tokens = await refresh_token_service.issue_session(db_session, user)
    headers = {"Authorization": f"Bearer {tokens.access_token}"}

    t0 = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    t1 = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    t3 = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
    t4 = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)

    # 1. Shipped order with distinct activity timestamps
    shipped_order = Order(
        number="IM-TRKACT1",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.SHIPPED.value,
        payment_method="cod",
        courier_name="Pathao",
        tracking_number="PTH-1001",
        customer_name=user.full_name,
        phone=user.phone or "",
        district="Dhaka",
        area="Uttara",
        address="Sector 7",
        delivery_zone="inside",
        subtotal=1000,
        shipping=60,
        total=1060,
        created_at=t0,
        updated_at=t4,
    )
    # 2. Cancelled order after confirmation
    cancelled_order = Order(
        number="IM-TRKCAN1",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.CANCELLED.value,
        payment_method="cod",
        customer_name=user.full_name,
        phone=user.phone or "",
        district="Dhaka",
        area="Uttara",
        address="Sector 7",
        delivery_zone="inside",
        subtotal=800,
        shipping=60,
        total=860,
        created_at=t0,
        updated_at=t2,
    )
    # 3. Returned order after delivery
    returned_order = Order(
        number="IM-TRKRET1",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.RETURNED.value,
        payment_method="cod",
        customer_name=user.full_name,
        phone=user.phone or "",
        district="Dhaka",
        area="Uttara",
        address="Sector 7",
        delivery_zone="inside",
        subtotal=900,
        shipping=60,
        total=960,
        created_at=t0,
        delivered_at=t3,
        returned_at=t4,
        updated_at=t4,
    )
    db_session.add_all([shipped_order, cancelled_order, returned_order])
    await db_session.flush()

    db_session.add_all(
        [
            OrderActivity(
                order_id=shipped_order.id,
                action=ActivityAction.STATUS_CHANGED.value,
                summary="Status new to confirmed",
                detail={"from": "new", "to": "confirmed"},
                created_at=t1,
            ),
            OrderActivity(
                order_id=shipped_order.id,
                action=ActivityAction.STATUS_CHANGED.value,
                summary="Status confirmed to packed",
                detail={"from": "confirmed", "to": "packed"},
                created_at=t2,
            ),
            OrderActivity(
                order_id=shipped_order.id,
                action=ActivityAction.STATUS_CHANGED.value,
                summary="Status packed to shipped",
                detail={"from": "packed", "to": "shipped"},
                created_at=t3,
            ),
            OrderActivity(
                order_id=cancelled_order.id,
                action=ActivityAction.STATUS_CHANGED.value,
                summary="Status new to confirmed",
                detail={"from": "new", "to": "confirmed"},
                created_at=t1,
            ),
            OrderActivity(
                order_id=cancelled_order.id,
                action=ActivityAction.STATUS_CHANGED.value,
                summary="Status confirmed to cancelled",
                detail={"from": "confirmed", "to": "cancelled"},
                created_at=t2,
            ),
            OrderActivity(
                order_id=returned_order.id,
                action=ActivityAction.STATUS_CHANGED.value,
                summary="Status delivered to returned",
                detail={"from": "delivered", "to": "returned"},
                created_at=t4,
            ),
        ]
    )
    await db_session.commit()

    # Check shipped order real timestamps & future-ready courier fields
    resp1 = await client.get(
        f"/api/v1/customer/orders/{shipped_order.number}/tracking", headers=headers
    )
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["tracking_url"] is None
    assert d1["live_events"] == []
    by_status = {s["status"]: s for s in d1["timeline"]}
    assert datetime.fromisoformat(by_status["new"]["timestamp"]) == t0
    assert datetime.fromisoformat(by_status["confirmed"]["timestamp"]) == t1
    assert datetime.fromisoformat(by_status["packed"]["timestamp"]) == t2
    assert datetime.fromisoformat(by_status["shipped"]["timestamp"]) == t3
    assert by_status["delivered"]["completed"] is False
    assert by_status["delivered"]["timestamp"] is None

    # Check cancelled order timeline (reached steps + cancelled terminal step)
    resp2 = await client.get(
        f"/api/v1/customer/orders/{cancelled_order.number}/tracking", headers=headers
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["status"] == "cancelled"
    assert [s["status"] for s in d2["timeline"]] == ["new", "confirmed", "cancelled"]
    assert all(s["completed"] is True for s in d2["timeline"])
    assert datetime.fromisoformat(d2["timeline"][1]["timestamp"]) == t1
    assert datetime.fromisoformat(d2["timeline"][2]["timestamp"]) == t2

    # Check returned order timeline (reached up to delivered + returned terminal step)
    resp3 = await client.get(
        f"/api/v1/customer/orders/{returned_order.number}/tracking", headers=headers
    )
    assert resp3.status_code == 200
    d3 = resp3.json()
    assert d3["status"] == "returned"
    assert [s["status"] for s in d3["timeline"]] == [
        "new",
        "confirmed",
        "packed",
        "shipped",
        "delivered",
        "returned",
    ]
    assert all(s["completed"] is True for s in d3["timeline"])
    assert datetime.fromisoformat(d3["timeline"][4]["timestamp"]) == t3
    assert datetime.fromisoformat(d3["timeline"][5]["timestamp"]) == t4


@pytest.mark.asyncio
async def test_purchased_products_full_history_and_payment_fields(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = User(
        full_name="Repeat Buyer",
        phone="01655667788",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
    )
    prod1 = Product(
        title="Repeat Cotton Panjabi",
        slug=f"repeat-panjabi-{uuid.uuid4().hex[:6]}",
        price=1500,
        status=StockStatus.AVAILABLE.value,
        content={},
        published=True,
    )
    prod2 = Product(
        title="Second Item Scarf",
        slug=f"second-scarf-{uuid.uuid4().hex[:6]}",
        price=600,
        status=StockStatus.AVAILABLE.value,
        content={},
        published=True,
    )
    db_session.add_all([user, prod1, prod2])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(prod1)
    await db_session.refresh(prod2)

    tokens = await refresh_token_service.issue_session(db_session, user)
    headers = {"Authorization": f"Bearer {tokens.access_token}"}

    t_older = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    t_mid = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    t_newer = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)

    # Order 1: COD due, qty 2 of prod1
    ord1 = Order(
        number="IM-PUR00001",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.CONFIRMED.value,
        payment_method="cod",
        paid_amount=0,
        due_amount=3060,
        customer_name=user.full_name,
        phone=user.phone or "",
        district="Dhaka",
        area="Mirpur",
        address="Test",
        delivery_zone="inside",
        subtotal=3000,
        shipping=60,
        total=3060,
        created_at=t_older,
    )
    ord1.items.append(
        OrderItem(
            product_id=prod1.id,
            title=prod1.title,
            slug=prod1.slug,
            unit_price=1500,
            quantity=2,
            line_total=3000,
            sku="P1",
        )
    )

    # Order 2: Bangla QR partial advance, repeat purchase qty 1 of prod1
    ord2 = Order(
        number="IM-PUR00002",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.SHIPPED.value,
        payment_method="bangla_qr",
        advance_percent=50,
        advance_amount=780,
        paid_amount=0,
        due_amount=780,
        customer_name=user.full_name,
        phone=user.phone or "",
        district="Dhaka",
        area="Mirpur",
        address="Test",
        delivery_zone="inside",
        subtotal=1500,
        shipping=60,
        total=1560,
        created_at=t_mid,
    )
    ord2.items.append(
        OrderItem(
            product_id=prod1.id,
            title=prod1.title,
            slug=prod1.slug,
            unit_price=1500,
            quantity=1,
            line_total=1500,
            sku="P1",
        )
    )

    # Order 3: Fully paid delivered order of prod2
    ord3 = Order(
        number="IM-PUR00003",
        user_id=user.id,
        source="direct",
        channel="website",
        status=OrderStatus.DELIVERED.value,
        payment_method="cod",
        paid_amount=660,
        due_amount=0,
        customer_name=user.full_name,
        phone=user.phone or "",
        district="Dhaka",
        area="Mirpur",
        address="Test",
        delivery_zone="inside",
        subtotal=600,
        shipping=60,
        total=660,
        created_at=t_newer,
    )
    ord3.items.append(
        OrderItem(
            product_id=prod2.id,
            title=prod2.title,
            slug=prod2.slug,
            unit_price=600,
            quantity=1,
            line_total=600,
            sku="P2",
        )
    )

    db_session.add_all([ord1, ord2, ord3])
    await db_session.commit()

    resp = await client.get("/api/v1/customer/purchased-products", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    # Must keep all 3 lines (repeat purchase of prod1 NOT dropped)
    assert len(items) == 3
    by_order = {row["order_number"]: row for row in items}

    r1 = by_order["IM-PUR00001"]
    assert r1["product_id"] == str(prod1.id)
    assert r1["quantity"] == 2
    assert r1["line_total"] == 3000
    assert r1["order_status"] == "confirmed"
    assert r1["paid_amount"] == 0
    assert r1["due_amount"] == 3060
    assert r1["payment_status"] == "cod_due"
    assert r1["can_review"] is True

    r2 = by_order["IM-PUR00002"]
    assert r2["product_id"] == str(prod1.id)
    assert r2["quantity"] == 1
    assert r2["line_total"] == 1500
    assert r2["order_status"] == "shipped"
    assert r2["paid_amount"] == 780
    assert r2["due_amount"] == 780
    assert r2["payment_status"] == "partial"
    assert r2["can_review"] is True

    r3 = by_order["IM-PUR00003"]
    assert r3["product_id"] == str(prod2.id)
    assert r3["quantity"] == 1
    assert r3["line_total"] == 600
    assert r3["order_status"] == "delivered"
    assert r3["paid_amount"] == 660
    assert r3["due_amount"] == 0
    assert r3["payment_status"] == "paid"
    assert r3["can_review"] is True

    # Review prod1 -> can_review becomes False on BOTH repeat lines of prod1, stays True for prod2
    rev_resp = await client.post(
        f"/api/v1/products/{prod1.id}/reviews",
        json={"rating": 5, "headline": "Great", "comment": "Bought twice and loved it."},
        headers=headers,
    )
    assert rev_resp.status_code == 201

    resp_after = await client.get("/api/v1/customer/purchased-products", headers=headers)
    assert resp_after.status_code == 200
    by_order_after = {row["order_number"]: row for row in resp_after.json()}
    assert by_order_after["IM-PUR00001"]["can_review"] is False
    assert by_order_after["IM-PUR00002"]["can_review"] is False
    assert by_order_after["IM-PUR00003"]["can_review"] is True
