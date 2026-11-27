"""Phase 32 tests: Dropshipping orders, atomic wallet ledger, T+3 unlock, RTO, payouts & P&L."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.courier import CourierShipment
from app.models.dropshipping import (
    DropshipperProfile,
    DropshipperWalletTransaction,
    WalletEntryType,
)
from app.models.order import Order, OrderStatus
from app.models.user import UserRole
from app.schemas.user import UserCreate
from app.services import (
    dropship_wallet_service,
    order_service,
    report_service,
    user_service,
)
from app.services.courier import steadfast_webhook_service
from tests.conftest import TEST_PASSWORD


async def _create_approved_dropshipper(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    phone: str = "01722334455",
    email: str = "ds1@example.com",
    shop_name: str = "Dhaka Trendz",
) -> tuple[dict[str, str], str, str]:
    """Register customer, apply & approve as dropshipper -> (headers, user_id, profile_id)."""
    reg = await client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Dropship Owner",
            "phone": phone,
            "email": email,
            "password": TEST_PASSWORD,
        },
    )
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    prof = await client.get("/api/v1/customer/profile", headers=headers)
    user_id = prof.json()["id"]

    apply_res = await client.post(
        "/api/v1/dropshipper/apply",
        headers=headers,
        json={
            "shop_name": shop_name,
            "shop_phone": phone,
            "shop_address": "Mirpur, Dhaka",
            "payout_method": "bkash",
            "payout_account_number": phone,
            "payout_account_name": "Dropship Owner",
        },
    )
    assert apply_res.status_code == 201, apply_res.text
    profile_id = apply_res.json()["id"]

    appr = await client.post(
        f"/api/v1/admin/dropshipping/partners/{profile_id}/approve",
        headers=auth_headers,
    )
    assert appr.status_code == 200, appr.text
    return headers, user_id, profile_id


async def _create_dropship_product(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    title: str = "Cotton Panjabi",
    cost_price: int = 300,
    dropship_price: int = 500,
    retail_price: int = 800,
    min_sell_price: int = 550,
    max_sell_price: int = 1200,
    quantity: int = 50,
) -> str:
    cat = await client.post(
        "/api/v1/admin/categories",
        headers=auth_headers,
        data={"payload": json.dumps({"name": f"Cat-{uuid.uuid4().hex[:6]}"})},
    )
    assert cat.status_code == 201, cat.text
    cat_id = cat.json()["id"]

    prod = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        data={
            "payload": json.dumps(
                {
                    "title": title,
                    "subtitle": "Premium fabric",
                    "category_id": cat_id,
                    "price": retail_price,
                    "cost_price": cost_price,
                    "quantity": quantity,
                    "weight_grams": 400,
                    "image_src": "/media/products/test-panjabi.jpg",
                    "published": True,
                    "allow_dropshipping": True,
                    "dropship_price": dropship_price,
                    "min_sell_price": min_sell_price,
                    "max_sell_price": max_sell_price,
                }
            )
        },
    )
    assert prod.status_code == 201, prod.text
    return str(prod.json()["id"])


async def _place_ds_order(
    client: AsyncClient,
    ds_headers: dict[str, str],
    product_id: str,
    *,
    selling_price: int = 800,
    quantity: int = 1,
    idem_key: str | None = None,
) -> dict:
    res = await client.post(
        "/api/v1/dropshipper/orders",
        headers={**ds_headers, "Idempotency-Key": idem_key or f"ds-key-{uuid.uuid4().hex}"},
        json={
            "items": [
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "selling_price": selling_price,
                }
            ],
            "district": "Dhaka",
            "area": "Dhanmondi",
            "delivery_zone": "dhaka_inside",
            "customer_name": "End Buyer",
            "phone": "01811223344",
            "address": "Road 10, Dhanmondi, Dhaka",
            "note": "Call before delivery",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _deliver_order(db_session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await db_session.scalar(select(Order).where(Order.id == order_id))
    assert order is not None
    for step in (
        OrderStatus.CONFIRMED.value,
        OrderStatus.PACKED.value,
        OrderStatus.SHIPPED.value,
        OrderStatus.DELIVERED.value,
    ):
        await order_service.change_status(db_session, order, step, actor_id=None)
        await db_session.refresh(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


async def _return_order(db_session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = (
        await db_session.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    assert order is not None
    for step in (
        OrderStatus.CONFIRMED.value,
        OrderStatus.PACKED.value,
        OrderStatus.SHIPPED.value,
        OrderStatus.RETURNED.value,
    ):
        await order_service.change_status(db_session, order, step, actor_id=None)
        await db_session.refresh(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


async def test_a_new_seller_active_order_cap_and_trusted_promotion(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    ds_headers, user_id, _profile_id = await _create_approved_dropshipper(
        client, auth_headers, phone="01722000001", email="cap@example.com"
    )
    product_id = await _create_dropship_product(client, auth_headers)

    # Quote works & returns profit breakdown
    quote = await client.post(
        "/api/v1/dropshipper/orders/quote",
        headers=ds_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1, "selling_price": 800}],
            "district": "Dhaka",
            "area": "Dhanmondi",
            "delivery_zone": "dhaka_inside",
        },
    )
    assert quote.status_code == 200, quote.text
    q_data = quote.json()
    assert q_data["wholesale_total"] == 500
    assert q_data["customer_subtotal"] == 800
    assert q_data["profit_amount"] == 300
    assert q_data["can_place_order"] is True

    # Place 3 active orders (default new_seller_max_active_orders = 3)
    placed_ids: list[uuid.UUID] = []
    for _ in range(3):
        order_data = await _place_ds_order(client, ds_headers, product_id)
        placed_ids.append(uuid.UUID(order_data["id"]))

    # 4th active order MUST be rejected for a "new" seller
    fourth = await client.post(
        "/api/v1/dropshipper/orders",
        headers={**ds_headers, "Idempotency-Key": f"fourth-{uuid.uuid4().hex}"},
        json={
            "items": [{"product_id": product_id, "quantity": 1, "selling_price": 800}],
            "district": "Dhaka",
            "area": "Dhanmondi",
            "delivery_zone": "dhaka_inside",
            "customer_name": "Fourth Buyer",
            "phone": "01811223399",
            "address": "House 4, Dhaka",
        },
    )
    assert fourth.status_code == 422, fourth.text
    assert "New seller limit reached" in fourth.text

    # Deliver all 3 orders, then place & deliver 2 more (5 deliveries => auto-promote to trusted)
    for oid in placed_ids:
        await _deliver_order(db_session, oid)

    for _ in range(2):
        od = await _place_ds_order(client, ds_headers, product_id)
        await _deliver_order(db_session, uuid.UUID(od["id"]))

    wallet = await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)
    assert wallet.status_code == 200
    w_data = wallet.json()
    assert w_data["delivered_count"] == 5
    assert w_data["tier"] == "trusted"

    # Now as a trusted seller, 4 simultaneous active orders succeed!
    for _ in range(4):
        await _place_ds_order(client, ds_headers, product_id)

    listed = await client.get("/api/v1/dropshipper/orders", headers=ds_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 9


async def test_b_delivered_pending_t3_unlock_and_webhook_idempotency(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    ds_headers, user_id, _profile_id = await _create_approved_dropshipper(
        client, auth_headers, phone="01722000002", email="unlock@example.com"
    )
    product_id = await _create_dropship_product(client, auth_headers)

    # Idempotency-Key replay on order creation
    idem = f"idem-{uuid.uuid4().hex}"
    o1 = await _place_ds_order(client, ds_headers, product_id, selling_price=850, idem_key=idem)
    o2 = await _place_ds_order(client, ds_headers, product_id, selling_price=850, idem_key=idem)
    assert o1["id"] == o2["id"]
    assert o1["profit_amount"] == 350

    order_uuid = uuid.UUID(o1["id"])
    order = await db_session.scalar(select(Order).where(Order.id == order_uuid))
    assert order is not None

    # Move order to shipped (as happens when Steadfast parcel is booked & dispatched)
    for step in (
        OrderStatus.CONFIRMED.value,
        OrderStatus.PACKED.value,
        OrderStatus.SHIPPED.value,
    ):
        await order_service.change_status(db_session, order, step, actor_id=None)
        await db_session.refresh(order)

    # Attach Steadfast shipment and deliver via Steadfast webhook
    shipment = CourierShipment(
        order_id=order.id,
        provider="steadfast",
        invoice=order.number,
        consignment_id="SF-DS-1001",
        tracking_code="TRK-DS-1001",
        cod_amount=order.total,
        delivery_status="in_review",
    )
    db_session.add(shipment)
    await db_session.commit()

    webhook_payload = {
        "notification_type": "delivery_status",
        "consignment_id": "SF-DS-1001",
        "invoice": order.number,
        "status": "delivered",
        "cod_amount": order.total,
        "tracking_message": "Parcel delivered to buyer",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    r1 = await steadfast_webhook_service.process_steadfast_webhook(db_session, webhook_payload)
    assert r1.status == "processed"

    # Duplicate webhook (even with different timestamp/event_key) MUST NOT double-credit!
    webhook_payload_dup = {
        **webhook_payload,
        "updated_at": (datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
    }
    r2 = await steadfast_webhook_service.process_steadfast_webhook(db_session, webhook_payload_dup)
    assert r2.ok is True

    # Also direct duplicate hook call MUST be a no-op
    await db_session.refresh(order)
    dup_credit = await dropship_wallet_service.on_dropship_order_delivered(db_session, order)
    assert dup_credit is False

    # Verify wallet: 350 in pending, 0 in available (not yet T+3)
    w_before = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert w_before["pending_balance"] == 350
    assert w_before["available_balance"] == 0
    assert w_before["total_earned"] == 350
    assert w_before["delivered_count"] == 1

    # Simulate T+3 maturity by backdating unlock_at to 1 hour ago
    pending_tx = await db_session.scalar(
        select(DropshipperWalletTransaction).where(
            DropshipperWalletTransaction.order_id == order_uuid,
            DropshipperWalletTransaction.entry_type == WalletEntryType.CREDIT_PENDING.value,
        )
    )
    assert pending_tx is not None
    pending_tx.unlock_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    # Calling GET /wallet automatically unlocks matured profit!
    w_after = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert w_after["pending_balance"] == 0
    assert w_after["available_balance"] == 350
    assert w_after["unlocked_just_now"] == 350

    # Calling GET /wallet again does NOT double-unlock
    w_again = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert w_again["available_balance"] == 350
    assert w_again["unlocked_just_now"] == 0

    # Tracking endpoint returns shipment events
    trk = await client.get(
        f"/api/v1/dropshipper/orders/{o1['number']}/tracking", headers=ds_headers
    )
    assert trk.status_code == 200
    assert trk.json()["consignment_id"] == "SF-DS-1001"
    assert trk.json()["delivery_status"] == "delivered"


async def test_c_rto_deduction_negative_limit_block_and_topup_recovery(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    ds_headers, user_id, _profile_id = await _create_approved_dropshipper(
        client, auth_headers, phone="01722000003", email="rto@example.com"
    )
    product_id = await _create_dropship_product(client, auth_headers)

    # Switch RTO mode to fixed 130 so 2 returns => -260 (below -200 limit!)
    patch_cfg = await client.patch(
        "/api/v1/admin/dropshipping/settings",
        headers=auth_headers,
        json={"rto_charge_mode": "fixed", "rto_fixed_fee": 130, "negative_wallet_limit": -200},
    )
    assert patch_cfg.status_code == 200

    o1 = await _place_ds_order(client, ds_headers, product_id)
    o2 = await _place_ds_order(client, ds_headers, product_id)
    await _return_order(db_session, uuid.UUID(o1["id"]))
    await _return_order(db_session, uuid.UUID(o2["id"]))

    wallet = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert wallet["available_balance"] == -260
    assert wallet["returned_count"] == 2
    assert wallet["is_blocked_negative_wallet"] is True

    # New order MUST be blocked due to negative wallet limit (-260 < -200)
    blocked = await client.post(
        "/api/v1/dropshipper/orders",
        headers={**ds_headers, "Idempotency-Key": f"blk-{uuid.uuid4().hex}"},
        json={
            "items": [{"product_id": product_id, "quantity": 1, "selling_price": 800}],
            "district": "Dhaka",
            "area": "Dhanmondi",
            "delivery_zone": "dhaka_inside",
            "customer_name": "Blocked Buyer",
            "phone": "01811223355",
            "address": "House 5, Dhaka",
        },
    )
    assert blocked.status_code == 422, blocked.text
    assert "Wallet Top-Up" in blocked.text

    # Submit Wallet Top-Up of 300 & approve via Admin -> balance becomes +40, unblocked!
    topup = await client.post(
        "/api/v1/dropshipper/topups",
        headers=ds_headers,
        json={
            "amount": 300,
            "payment_method": "bkash",
            "sender_number": "01722000003",
            "transaction_id": "TRX998877",
        },
    )
    assert topup.status_code == 201, topup.text
    topup_id = topup.json()["id"]

    appr = await client.post(
        f"/api/v1/admin/dropshipping/topups/{topup_id}/approve",
        headers=auth_headers,
        json={"admin_note": "Verified on bKash"},
    )
    assert appr.status_code == 200, appr.text
    assert appr.json()["status"] == "approved"

    wallet_after = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert wallet_after["available_balance"] == 40
    assert wallet_after["is_blocked_negative_wallet"] is False

    # Placing a new order succeeds again!
    o3 = await _place_ds_order(client, ds_headers, product_id)
    assert o3["status"] == "new"


async def test_d_payout_lock_mark_paid_reject_refund_and_superadmin_adjust(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    ds_headers, user_id, profile_id = await _create_approved_dropshipper(
        client, auth_headers, phone="01722000004", email="payout@example.com"
    )

    # Superadmin credits 1500 to available balance
    adj = await client.post(
        f"/api/v1/admin/dropshipping/wallets/{profile_id}/adjust",
        headers=auth_headers,
        json={"amount": 1500, "reason": "Opening bonus credit"},
    )
    assert adj.status_code == 200, adj.text
    assert adj.json()["available_balance"] == 1500

    # Non-superadmin (editor) MUST be blocked from manual wallet adjust
    await user_service.create_user(
        db_session,
        UserCreate(
            email="editor.ds@example.com",
            full_name="Editor User",
            password=TEST_PASSWORD,
            role=UserRole.EDITOR.value,
        ),
    )
    ed_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "editor.ds@example.com", "password": TEST_PASSWORD},
    )
    assert ed_login.status_code == 200
    ed_headers = {"Authorization": f"Bearer {ed_login.json()['access_token']}"}
    ed_adj = await client.post(
        f"/api/v1/admin/dropshipping/wallets/{profile_id}/adjust",
        headers=ed_headers,
        json={"amount": 100, "reason": "Unauthorized"},
    )
    assert ed_adj.status_code == 403

    # Request payout #1 (600) -> available 900, locked 600
    p1 = await client.post(
        "/api/v1/dropshipper/payouts",
        headers=ds_headers,
        json={"amount": 600},
    )
    assert p1.status_code == 201, p1.text
    p1_id = p1.json()["id"]

    # Request payout #2 (500) -> available 400, locked 1100
    p2 = await client.post(
        "/api/v1/dropshipper/payouts",
        headers=ds_headers,
        json={"amount": 500},
    )
    assert p2.status_code == 201, p2.text
    p2_id = p2.json()["id"]

    w_mid = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert w_mid["available_balance"] == 400
    assert w_mid["locked_withdrawal_balance"] == 1100

    # Admin marks payout #1 PAID -> locked 500, total_withdrawn 600
    paid = await client.post(
        f"/api/v1/admin/dropshipping/payouts/{p1_id}/mark-paid",
        headers=auth_headers,
        json={"transaction_id": "BKASH-PAY-001", "admin_note": "Sent"},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"

    # Admin REJECTS payout #2 -> locked 0, available refunded to 900!
    rej = await client.post(
        f"/api/v1/admin/dropshipping/payouts/{p2_id}/reject",
        headers=auth_headers,
        json={"reason": "Invalid account number"},
    )
    assert rej.status_code == 200, rej.text
    assert rej.json()["status"] == "rejected"

    w_end = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert w_end["available_balance"] == 900
    assert w_end["locked_withdrawal_balance"] == 0
    assert w_end["total_withdrawn"] == 600

    # Fraud-check endpoint works for approved dropshipper
    fc = await client.get(
        "/api/v1/dropshipper/fraud-check",
        headers=ds_headers,
        params={"phone": "01811223344"},
    )
    assert fc.status_code == 200, fc.text
    assert "totals" in fc.json()


async def test_e_pnl_sync_counts_dropship_wholesale_and_leaves_retail_untouched(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    ds_headers, _user_id, _profile_id = await _create_approved_dropshipper(
        client, auth_headers, phone="01722000005", email="pnl@example.com"
    )
    # Product: cost_price=300, dropship_price=500, retail_price=800
    product_id = await _create_dropship_product(
        client,
        auth_headers,
        cost_price=300,
        dropship_price=500,
        retail_price=800,
        min_sell_price=500,
        max_sell_price=1500,
    )

    # Configure flat packaging fee = 20 so platform_fee = 20
    await client.patch(
        "/api/v1/admin/dropshipping/settings",
        headers=auth_headers,
        json={"platform_fee_percent": 0, "packaging_fee_flat": 20},
    )

    # 1. Place & deliver a dropship order with selling_price = 900 (qty 1)
    #    Implesia Mart revenue = wholesale (500) + platform_fee (20) = 520
    #    Dropshipper profit = 900 - 500 - 20 = 380
    #    Implesia Mart COGS = 300 => Implesia Mart profit = 220!
    ds_order = await _place_ds_order(client, ds_headers, product_id, selling_price=900)
    assert ds_order["wholesale_total"] == 500
    assert ds_order["platform_fee"] == 20
    assert ds_order["profit_amount"] == 380
    await _deliver_order(db_session, uuid.UUID(ds_order["id"]))

    req = report_service.ReportRequest(preset="this_month")
    pnl_ds_only = await report_service.profit_loss_report(db_session, req)
    prof_ds_only = await report_service.profit_report(db_session, req)

    assert prof_ds_only.revenue == 520
    assert int(prof_ds_only.cost or 0) == 300
    assert int(prof_ds_only.profit or 0) == 220
    assert pnl_ds_only.gross_sales == 520
    assert int(pnl_ds_only.gross_profit or 0) == 220

    # 2. Place & deliver a regular retail order (dropshipper_id IS NULL) at retail_price = 800
    #    Retail revenue = 800, COGS = 300 => Retail profit = 500
    #    Combined: revenue = 520 + 800 = 1320, COGS = 600, profit = 720!
    retail_res = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"retail-{uuid.uuid4().hex}"},
        json={
            "source": "direct",
            "items": [{"product_id": product_id, "quantity": 1}],
            "customer_name": "Retail Buyer",
            "phone": "01911223344",
            "district": "Dhaka",
            "area": "Gulshan",
            "address": "House 1, Gulshan",
            "delivery_zone": "inside",
            "payment_method": "cod",
        },
    )
    assert retail_res.status_code == 201, retail_res.text
    retail_id = uuid.UUID(retail_res.json()["id"])
    await _deliver_order(db_session, retail_id)

    prof_combined = await report_service.profit_report(db_session, req)
    assert prof_combined.revenue == 1320
    assert int(prof_combined.cost or 0) == 600
    assert int(prof_combined.profit or 0) == 720

    # Verify dropshipper profile counters were not affected by the retail order
    profile = await db_session.scalar(
        select(DropshipperProfile).where(DropshipperProfile.id == uuid.UUID(_profile_id))
    )
    assert profile is not None
    assert profile.delivered_count == 1
    assert profile.pending_balance == 380
