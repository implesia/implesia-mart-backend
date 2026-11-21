"""Phase C Admin-Only (RequireSuperadmin) safe deletion with impact analysis & reconciliation."""

import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditAction, AuditEvent
from app.models.badge import Badge
from app.models.coupon import CouponRedemption
from app.models.inventory import Purchase, StockMovement, Supplier
from app.models.notification import CustomerNotification
from app.models.order import Order, OrderActivity
from app.models.product import Product
from app.models.review import ProductReview
from tests.test_orders import SHIPPING, _key, _move

ADMIN_ORDERS = "/api/v1/admin/orders"
ADMIN_BADGES = "/api/v1/admin/badges"
ADMIN_INVENTORY = "/api/v1/admin/inventory"
ADMIN_PRODUCTS = "/api/v1/admin/products"
ADMIN_COUPONS = "/api/v1/admin/coupons"
ADMIN_REPORTS = "/api/v1/admin/reports"


async def _staff_headers(
    client: AsyncClient, superadmin_headers: dict[str, str], *, email: str, role: str
) -> dict[str, str]:
    created = await client.post(
        "/api/v1/users",
        headers=superadmin_headers,
        json={
            "email": email,
            "full_name": f"Test {role.title()}",
            "password": "staff-passphrase-123",
            "role": role,
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "staff-passphrase-123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_product(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str,
    price: int = 500,
    quantity: int = 10,
    cost_price: str = "300.00",
    supplier_id: str | None = None,
    badge_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "category": "gadgets",
        "price": price,
        "quantity": quantity,
        "cost_price": cost_price,
        "published": True,
        "image_src": "/uploads/phase-c.png",
    }
    if supplier_id is not None:
        payload["supplier_id"] = supplier_id
    if badge_ids is not None:
        payload["badge_ids"] = badge_ids
    res = await client.post(
        ADMIN_PRODUCTS,
        headers=headers,
        data={"payload": json.dumps(payload)},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_supplier(
    client: AsyncClient, headers: dict[str, str], name: str, phone: str = "01711110000"
) -> dict[str, Any]:
    res = await client.post(
        f"{ADMIN_INVENTORY}/suppliers",
        headers=headers,
        json={"name": name, "phone": phone, "address": "Dhaka", "note": ""},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_phase_c_rbac_blocks_editor_and_viewer(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    editor_headers = await _staff_headers(
        client, auth_headers, email="phase-c-editor@implesia.com", role="editor"
    )
    viewer_headers = await _staff_headers(
        client, auth_headers, email="phase-c-viewer@implesia.com", role="viewer"
    )

    sup = await _create_supplier(client, auth_headers, "RBAC Supplier")
    prod = await _create_product(client, auth_headers, title="RBAC Item", supplier_id=sup["id"])
    badge_res = await client.post(
        ADMIN_BADGES, headers=auth_headers, json={"name": "RBAC Badge"}
    )
    assert badge_res.status_code == 201, badge_res.text
    badge = badge_res.json()

    order_res = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": prod["id"], "quantity": 1}],
            **SHIPPING,
            "phone": "01712345678",
        },
    )
    assert order_res.status_code == 201, order_res.text
    order = order_res.json()

    # Editor AND viewer must get 403 on all 6 delete / delete-impact endpoints
    for staff_hdrs in (editor_headers, viewer_headers):
        assert (
            await client.get(f"{ADMIN_ORDERS}/{order['id']}/delete-impact", headers=staff_hdrs)
        ).status_code == 403
        assert (
            await client.request(
                "DELETE",
                f"{ADMIN_ORDERS}/{order['id']}",
                headers=staff_hdrs,
                json={"confirm": True, "reconcile_stock": True, "reason": "Test delete"},
            )
        ).status_code == 403
        assert (
            await client.get(f"{ADMIN_BADGES}/{badge['id']}/delete-impact", headers=staff_hdrs)
        ).status_code == 403
        assert (
            await client.delete(f"{ADMIN_BADGES}/{badge['id']}", headers=staff_hdrs)
        ).status_code == 403
        assert (
            await client.get(
                f"{ADMIN_INVENTORY}/suppliers/{sup['id']}/delete-impact", headers=staff_hdrs
            )
        ).status_code == 403
        assert (
            await client.delete(f"{ADMIN_INVENTORY}/suppliers/{sup['id']}", headers=staff_hdrs)
        ).status_code == 403


async def test_order_delete_impact_and_atomic_reconciliation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    prod = await _create_product(
        client, auth_headers, title="Ledger Watch", price=1000, quantity=10, cost_price="600.00"
    )
    # Record opening stock so sum(stock_movements) == physical stock (10)
    opening = await client.post(f"{ADMIN_INVENTORY}/opening-stock", headers=auth_headers)
    assert opening.status_code == 200, opening.text

    # Create a coupon so we can verify coupon release
    coupon_res = await client.post(
        ADMIN_COUPONS,
        headers=auth_headers,
        json={
            "code": "DELTEST50",
            "discount_type": "fixed",
            "value": "50",
            "usage_limit_total": 1,
            "is_active": True,
        },
    )
    assert coupon_res.status_code == 201, coupon_res.text

    # Register a customer so notifications & review can reference the order
    reg = await client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Delete Buyer",
            "phone": "01799887766",
            "password": "buyer-password-123",
        },
    )
    assert reg.status_code == 201, reg.text
    cust_headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    # Place an order for 3 units with the coupon (stock: 10 -> 7; movements: +10, -3 => sum 7)
    order_res = await client.post(
        "/api/v1/orders",
        headers={**cust_headers, "Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": prod["id"], "quantity": 3}],
            **SHIPPING,
            "phone": "01799887766",
            "coupon_code": "DELTEST50",
        },
    )
    assert order_res.status_code == 201, order_res.text
    order = order_res.json()
    order_uuid = uuid.UUID(order["id"])

    # Deliver order so it counts in reports and customer can review it
    for st in ("confirmed", "packed", "shipped", "delivered"):
        mv = await _move(client, auth_headers, order["id"], st)
        assert mv.status_code == 200, mv.text

    rev_res = await client.post(
        f"/api/v1/products/{prod['id']}/reviews",
        headers=cust_headers,
        json={"rating": 5, "headline": "Nice", "comment": "Great watch!"},
    )
    assert rev_res.status_code == 201, rev_res.text
    review_id = uuid.UUID(rev_res.json()["id"])

    # 1. Inspect delete-impact
    impact_res = await client.get(
        f"{ADMIN_ORDERS}/{order['id']}/delete-impact", headers=auth_headers
    )
    assert impact_res.status_code == 200, impact_res.text
    impact = impact_res.json()
    assert impact["order_number"] == order["number"]
    assert impact["status"] == "delivered"
    assert impact["inventory_held"] is True
    assert len(impact["stock_restore_items"]) == 1
    assert impact["stock_restore_items"][0]["quantity"] == 3
    assert impact["stock_movements_count"] == 1
    assert impact["coupon_redemption_code"] == "DELTEST50"
    assert impact["reviews_count"] == 1
    assert impact["notifications_count"] >= 1
    assert "Sales" in impact["report_impact_warning"]

    # confirm=false must be rejected (422)
    bad = await client.request(
        "DELETE",
        f"{ADMIN_ORDERS}/{order['id']}",
        headers=auth_headers,
        json={"confirm": False, "reconcile_stock": True, "reason": "Duplicate test order"},
    )
    assert bad.status_code == 422

    # 2. Perform atomic delete with stock reconciliation
    del_res = await client.request(
        "DELETE",
        f"{ADMIN_ORDERS}/{order['id']}",
        headers=auth_headers,
        json={"confirm": True, "reconcile_stock": True, "reason": "Duplicate test order"},
    )
    assert del_res.status_code == 200, del_res.text
    deleted = del_res.json()
    assert deleted == {
        "deleted_order_number": order["number"],
        "stock_restored_units": 3,
        "coupon_released": True,
        "reports_synced": True,
    }

    # Order is gone
    assert await db_session.get(Order, order_uuid) is None
    gone_res = await client.get(f"{ADMIN_ORDERS}/{order['id']}", headers=auth_headers)
    assert gone_res.status_code == 404

    # Physical stock == 10 AND immutable stock_movements ledger sum == 10!
    prod_uuid = uuid.UUID(prod["id"])
    refreshed_prod = await db_session.get(Product, prod_uuid, populate_existing=True)
    assert refreshed_prod is not None
    assert refreshed_prod.quantity == 10

    ledger_sum = int(
        await db_session.scalar(
            select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
                StockMovement.product_id == prod_uuid
            )
        )
        or 0
    )
    assert ledger_sum == 10

    # Reconciliation adjustment movement exists with clear note and order_id=None
    adj = (
        await db_session.scalars(
            select(StockMovement).where(
                StockMovement.product_id == prod_uuid,
                StockMovement.movement_type == "adjustment",
            )
        )
    ).all()
    assert len(adj) == 1
    assert adj[0].quantity == 3
    assert adj[0].order_id is None
    assert f"#{order['number']}" in adj[0].note
    assert "Duplicate test order" in adj[0].note

    # Cascade children removed; SET NULL references preserved with order_id=None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(OrderActivity)
            .where(OrderActivity.order_id == order_uuid)
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CouponRedemption)
            .where(CouponRedemption.order_id == order_uuid)
        )
        == 0
    )
    review_row = await db_session.get(ProductReview, review_id, populate_existing=True)
    assert review_row is not None
    assert review_row.order_id is None
    notifs = (
        await db_session.scalars(
            select(CustomerNotification).where(CustomerNotification.order_id == order_uuid)
        )
    ).all()
    assert len(notifs) == 0

    # Complete audit snapshot recorded
    audit_row = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == AuditAction.ORDER_DELETED.value,
                AuditEvent.target_id == str(order_uuid),
            )
        )
    ).first()
    assert audit_row is not None
    assert audit_row.event_metadata["order_number"] == order["number"]
    assert audit_row.event_metadata["reason"] == "Duplicate test order"
    assert audit_row.event_metadata["stock_restored_units"] == 3
    assert len(audit_row.event_metadata["items"]) == 1

    # Sales/P&L reports reflect deletion immediately (0 realized orders today)
    pnl = (
        await client.get(
            f"{ADMIN_REPORTS}/profit-loss", headers=auth_headers, params={"preset": "today"}
        )
    ).json()
    assert pnl["gross_sales"] == 0
    assert pnl["net_realized_sales"] == 0


async def test_badge_delete_impact_merge_and_unlink(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # Seed system badges
    sys_new = Badge(name="New", slug="new", tone="primary", is_system=True)
    db_session.add(sys_new)
    await db_session.commit()

    old_b = (
        await client.post(ADMIN_BADGES, headers=auth_headers, json={"name": "Flash Deal"})
    ).json()
    target_b = (
        await client.post(ADMIN_BADGES, headers=auth_headers, json={"name": "Hot Deal"})
    ).json()
    unlink_b = (
        await client.post(ADMIN_BADGES, headers=auth_headers, json={"name": "Temp Tag"})
    ).json()

    # Product 1 has only old_b; Product 2 already has BOTH old_b and target_b (dedupe check)
    p1 = await _create_product(
        client, auth_headers, title="Badge P1", badge_ids=[old_b["id"], unlink_b["id"]]
    )
    p2 = await _create_product(
        client, auth_headers, title="Badge P2", badge_ids=[old_b["id"], target_b["id"]]
    )

    # 1. Inspect impact
    imp = (
        await client.get(f"{ADMIN_BADGES}/{old_b['id']}/delete-impact", headers=auth_headers)
    ).json()
    assert imp["badge_name"] == "Flash Deal"
    assert imp["is_system"] is False
    assert imp["linked_products_count"] == 2
    assert {p["title"] for p in imp["sample_products"]} == {"Badge P1", "Badge P2"}
    assert any(t["id"] == target_b["id"] for t in imp["available_merge_targets"])

    # System badge cannot be deleted (409)
    sys_del = await client.request(
        "DELETE",
        f"{ADMIN_BADGES}/{sys_new.id}",
        headers=auth_headers,
        json={"mode": "unlink"},
    )
    assert sys_del.status_code == 409

    # Self-merge rejected (422)
    self_merge = await client.request(
        "DELETE",
        f"{ADMIN_BADGES}/{old_b['id']}",
        headers=auth_headers,
        json={"mode": "merge", "target_badge_id": old_b["id"]},
    )
    assert self_merge.status_code == 422

    # 2. Merge old_b -> target_b (deduplicating p2 cleanly)
    merged = await client.request(
        "DELETE",
        f"{ADMIN_BADGES}/{old_b['id']}",
        headers=auth_headers,
        json={"mode": "merge", "target_badge_id": target_b["id"]},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["mode"] == "merge"
    assert merged.json()["affected_products_count"] == 2
    assert merged.json()["target_badge_id"] == target_b["id"]

    # Both P1 and P2 now carry target_b without duplicates, and old_b is deleted
    p1_after = (await client.get(f"{ADMIN_PRODUCTS}/{p1['id']}", headers=auth_headers)).json()
    p2_after = (await client.get(f"{ADMIN_PRODUCTS}/{p2['id']}", headers=auth_headers)).json()
    assert {b["id"] for b in p1_after["badges"]} == {target_b["id"], unlink_b["id"]}
    assert [b["id"] for b in p2_after["badges"]] == [target_b["id"]]
    old_gone = await client.get(f"{ADMIN_BADGES}/{old_b['id']}", headers=auth_headers)
    assert old_gone.status_code == 404

    # 3. Unlink unlink_b from P1
    unlinked = await client.request(
        "DELETE",
        f"{ADMIN_BADGES}/{unlink_b['id']}",
        headers=auth_headers,
        json={"mode": "unlink"},
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["mode"] == "unlink"
    assert unlinked.json()["affected_products_count"] == 1
    p1_final = (await client.get(f"{ADMIN_PRODUCTS}/{p1['id']}", headers=auth_headers)).json()
    assert [b["id"] for b in p1_final["badges"]] == [target_b["id"]]

    # Audit events logged
    audit_count = int(
        await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == AuditAction.BADGE_DELETED.value)
        )
        or 0
    )
    assert audit_count == 2


async def test_supplier_delete_impact_merge_archive_and_hard_delete(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    sup_old = await _create_supplier(client, auth_headers, "Old Vendor")
    sup_new = await _create_supplier(client, auth_headers, "Main Vendor")
    sup_arch = await _create_supplier(client, auth_headers, "Archive Vendor")
    sup_empty = await _create_supplier(client, auth_headers, "Unused Vendor")

    p_old = await _create_product(
        client, auth_headers, title="Vendor Item", supplier_id=sup_old["id"]
    )
    p_arch = await _create_product(
        client, auth_headers, title="Arch Item", supplier_id=sup_arch["id"]
    )
    p_empty = await _create_product(
        client, auth_headers, title="Empty Vendor Item", supplier_id=sup_empty["id"]
    )

    # Record purchase under sup_old (4 units @ 250 = 1000) and sup_arch (2 units @ 100 = 200)
    purch_old = (
        await client.post(
            f"{ADMIN_INVENTORY}/purchases",
            headers=auth_headers,
            json={
                "supplier_id": sup_old["id"],
                "purchased_on": "2026-11-10",
                "invoice_no": "INV-OLD-1",
                "items": [{"product_id": p_old["id"], "quantity": 4, "unit_cost": "250.00"}],
            },
        )
    ).json()
    purch_arch = (
        await client.post(
            f"{ADMIN_INVENTORY}/purchases",
            headers=auth_headers,
            json={
                "supplier_id": sup_arch["id"],
                "purchased_on": "2026-11-10",
                "invoice_no": "INV-ARCH-1",
                "items": [{"product_id": p_arch["id"], "quantity": 2, "unit_cost": "100.00"}],
            },
        )
    ).json()

    # 1. Impact check on sup_old
    imp = (
        await client.get(
            f"{ADMIN_INVENTORY}/suppliers/{sup_old['id']}/delete-impact", headers=auth_headers
        )
    ).json()
    assert imp["supplier_name"] == "Old Vendor"
    assert imp["purchases_count"] == 1
    assert imp["total_purchase_amount"] == 1000.0
    assert imp["linked_products_count"] == 1
    assert any(t["id"] == sup_new["id"] for t in imp["available_merge_targets"])

    # Hard delete with purchases must fail (409)
    blocked = await client.request(
        "DELETE",
        f"{ADMIN_INVENTORY}/suppliers/{sup_old['id']}",
        headers=auth_headers,
        json={"mode": "hard_delete"},
    )
    assert blocked.status_code == 409

    # 2. Merge sup_old -> sup_new (moves purchases & products, hard-deletes sup_old)
    merged = await client.request(
        "DELETE",
        f"{ADMIN_INVENTORY}/suppliers/{sup_old['id']}",
        headers=auth_headers,
        json={"mode": "merge", "target_supplier_id": sup_new["id"], "reason": "Duplicate vendor"},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["mode"] == "merge"
    assert merged.json()["moved_purchases_count"] == 1
    assert merged.json()["moved_products_count"] == 1

    # sup_old row is physically deleted; purchase & product now belong to sup_new
    assert await db_session.get(Supplier, uuid.UUID(sup_old["id"])) is None
    moved_purch = await db_session.get(Purchase, uuid.UUID(purch_old["id"]), populate_existing=True)
    assert moved_purch is not None
    assert str(moved_purch.supplier_id) == sup_new["id"]
    moved_prod = await db_session.get(Product, uuid.UUID(p_old["id"]), populate_existing=True)
    assert moved_prod is not None
    assert str(moved_prod.supplier_id) == sup_new["id"]

    # 3. Archive sup_arch (keeps historical purchase, unlinks product, soft-deletes supplier)
    archived = await client.request(
        "DELETE",
        f"{ADMIN_INVENTORY}/suppliers/{sup_arch['id']}",
        headers=auth_headers,
        json={"mode": "archive", "reason": "Inactive"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["mode"] == "archive"
    assert archived.json()["unlinked_products_count"] == 1

    arch_sup_row = await db_session.get(
        Supplier, uuid.UUID(sup_arch["id"]), populate_existing=True
    )
    assert arch_sup_row is not None and arch_sup_row.is_deleted is True
    arch_purch = await db_session.get(Purchase, uuid.UUID(purch_arch["id"]), populate_existing=True)
    assert arch_purch is not None and str(arch_purch.supplier_id) == sup_arch["id"]
    arch_prod = await db_session.get(Product, uuid.UUID(p_arch["id"]), populate_existing=True)
    assert arch_prod is not None and arch_prod.supplier_id is None

    # 4. Hard-delete sup_empty (0 purchases -> allowed, unlinks p_empty, deletes row)
    hard = await client.request(
        "DELETE",
        f"{ADMIN_INVENTORY}/suppliers/{sup_empty['id']}",
        headers=auth_headers,
        json={"mode": "hard_delete", "reason": "Created by mistake"},
    )
    assert hard.status_code == 200, hard.text
    assert hard.json()["mode"] == "hard_delete"
    assert hard.json()["unlinked_products_count"] == 1
    assert await db_session.get(Supplier, uuid.UUID(sup_empty["id"])) is None
    empty_prod = await db_session.get(Product, uuid.UUID(p_empty["id"]), populate_existing=True)
    assert empty_prod is not None and empty_prod.supplier_id is None

    # Audit events recorded for merge + archive + hard_delete
    merge_audits = int(
        await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == AuditAction.SUPPLIER_MERGED.value)
        )
        or 0
    )
    del_audits = int(
        await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == AuditAction.SUPPLIER_DELETED.value)
        )
        or 0
    )
    assert merge_audits == 1
    assert del_audits == 2
