import io
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User, UserRole
from app.services import customer_auth_service, notification_service, refresh_token_service


@pytest.mark.asyncio
async def test_notifications_flow(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
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
    db: AsyncSession,
) -> None:
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
        published=True,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    order = Order(
        number="IM-TRACK01",
        user_id=user.id,
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
    db: AsyncSession,
) -> None:
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
        published=True,
    )
    db.add_all([user1, user2, product])
    await db.commit()
    await db.refresh(user1)
    await db.refresh(user2)
    await db.refresh(product)

    order = Order(
        number="IM-REV01",
        user_id=user2.id,
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
        product_id=product.id,
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
        f"/api/v1/products/{product.id}/can-review",
        headers={"Authorization": f"Bearer {tokens1.access_token}"},
    )
    assert can_resp1.status_code == 200
    assert can_resp1.json()["can_review"] is False

    # User 2 can review
    can_resp2 = await client.get(
        f"/api/v1/products/{product.id}/can-review",
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
        f"/api/v1/products/{product.id}/reviews",
        json=review_payload,
        headers={"Authorization": f"Bearer {tokens2.access_token}"},
    )
    assert rev_post.status_code == 201
    rev_data = rev_post.json()
    assert rev_data["rating"] == 5
    assert rev_data["user_name"] == user2.full_name
    assert rev_data["is_verified_purchase"] is True

    # User 2 tries to review again -> ConflictError (409)
    rev_post_again = await client.post(
        f"/api/v1/products/{product.id}/reviews",
        json=review_payload,
        headers={"Authorization": f"Bearer {tokens2.access_token}"},
    )
    assert rev_post_again.status_code == 409

    # Public review list & summary
    pub_list = await client.get(f"/api/v1/products/{product.id}/reviews")
    assert pub_list.status_code == 200
    pub_data = pub_list.json()
    assert pub_data["total"] == 1
    assert pub_data["summary"]["average_rating"] == 5.0
    assert pub_data["summary"]["total_reviews"] == 1
    assert pub_data["summary"]["rating_histogram"]["5"] == 1


@pytest.mark.asyncio
async def test_avatar_upload(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
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
