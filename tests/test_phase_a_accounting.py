"""Phase A backend schema & accounting fixes:
1. Optional supplier_id on products + per-variant cost_price (admin only, never public)
   + weighted-average variant cost update in inventory purchases + variant cost snapshots on orders.
2. Offline order initial_status / mark_delivered with business-date delivered_at alignment,
   automatic customer user_id linking by phone, and payment collection via POST /payments & PATCH.
3. Returned-order exclusion from realized sales/profit/product/trend + manual_discount exposure.
"""

import json
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from app.models.product import ProductVariant

ADMIN_PRODUCTS = "/api/v1/admin/products"
ADMIN_ORDERS = "/api/v1/admin/orders"
ADMIN_INVENTORY = "/api/v1/admin/inventory"


async def _create_supplier(
    client: AsyncClient, auth_headers: dict[str, str], name: str
) -> dict[str, Any]:
    res = await client.post(
        f"{ADMIN_INVENTORY}/suppliers",
        headers=auth_headers,
        json={"name": name, "phone": "01711112222", "address": "Dhaka", "note": ""},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_product(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    title: str,
    price: int = 1000,
    quantity: int = 10,
    cost_price: str | None = "400.00",
    supplier_id: str | None = None,
    options: list[dict[str, Any]] | None = None,
    variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "category": "gadgets",
        "price": price,
        "quantity": quantity,
        "weight_grams": 500,
        "published": True,
        "image_src": "/uploads/phase-a.png",
        "content": {"options": options or []},
    }
    if cost_price is not None:
        payload["cost_price"] = cost_price
    if supplier_id is not None:
        payload["supplier_id"] = supplier_id
    if variants is not None:
        payload["variants"] = variants
    res = await client.post(
        ADMIN_PRODUCTS,
        headers=auth_headers,
        data={"payload": json.dumps(payload)},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_product_supplier_and_variant_cost_privacy_and_orders(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    sup_a = await _create_supplier(client, auth_headers, "Alpha Textiles")
    sup_b = await _create_supplier(client, auth_headers, "Beta Gadgets")
    deleted_sup = await _create_supplier(client, auth_headers, "Deleted Vendor")
    del_res = await client.delete(
        f"{ADMIN_INVENTORY}/suppliers/{deleted_sup['id']}", headers=auth_headers
    )
    assert del_res.status_code == 200

    # Creating a product with a soft-deleted supplier fails cleanly.
    bad = await client.post(
        ADMIN_PRODUCTS,
        headers=auth_headers,
        data={
            "payload": json.dumps(
                {
                    "title": "Bad Supplier Item",
                    "category": "gadgets",
                    "price": 500,
                    "weight_grams": 500,
                    "supplier_id": deleted_sup["id"],
                    "published": True,
                    "image_src": "/uploads/bad.png",
                }
            )
        },
    )
    assert bad.status_code == 400
    assert bad.json()["errors"][0]["field"] == "supplier"

    options = [
        {
            "id": "size",
            "name": "Size",
            "kind": "size",
            "values": [
                {"id": "s", "label": "S"},
                {"id": "l", "label": "L"},
            ],
        }
    ]
    variants = [
        {
            "options": {"size": "s"},
            "sku": "PH-A-S",
            "price": 1000,
            "cost_price": "350.50",
            "quantity": 10,
            "is_active": True,
        },
        {
            "options": {"size": "l"},
            "sku": "PH-A-L",
            "price": 1200,
            "cost_price": None,  # falls back to product cost_price
            "quantity": 10,
            "is_active": True,
        },
    ]
    prod = await _create_product(
        client,
        auth_headers,
        title="Variant Jacket",
        price=1000,
        cost_price="500.00",
        supplier_id=sup_a["id"],
        options=options,
        variants=variants,
    )
    assert prod["supplier_id"] == sup_a["id"]
    assert prod["supplier_name"] == "Alpha Textiles"
    assert prod["supplier"] == {"id": sup_a["id"], "name": "Alpha Textiles"}

    by_sku = {v["sku"]: v for v in prod["variants"]}
    assert by_sku["PH-A-S"]["cost_price"] == 350.5
    assert by_sku["PH-A-L"]["cost_price"] is None

    # Filter admin product list by supplier_id.
    other = await _create_product(
        client, auth_headers, title="Other Vendor Mug", supplier_id=sup_b["id"]
    )
    filtered = await client.get(
        ADMIN_PRODUCTS, headers=auth_headers, params={"supplier_id": sup_a["id"]}
    )
    assert filtered.status_code == 200
    ids = {row["id"] for row in filtered.json()["items"]}
    assert prod["id"] in ids
    assert other["id"] not in ids
    card = next(row for row in filtered.json()["items"] if row["id"] == prod["id"])
    assert card["supplier_id"] == sup_a["id"]
    assert card["supplier_name"] == "Alpha Textiles"

    # Public storefront list and detail must NEVER expose supplier or cost_price.
    pub_detail = await client.get(f"/api/v1/products/{prod['id']}")
    assert pub_detail.status_code == 200
    pub_json = pub_detail.json()
    for forbidden in ("supplier_id", "supplier_name", "supplier", "cost_price"):
        assert forbidden not in pub_json
    for pub_variant in pub_json["variants"]:
        assert "cost_price" not in pub_variant

    pub_list = await client.get("/api/v1/products")
    assert pub_list.status_code == 200
    for pub_card in pub_list.json()["items"]:
        for forbidden in ("supplier_id", "supplier_name", "supplier", "cost_price"):
            assert forbidden not in pub_card

    # Online checkout snapshots variant.cost_price when set, else product.cost_price.
    online_res = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"online-{secrets.token_hex(6)}"},
        json={
            "source": "direct",
            "customer_name": "Online Buyer",
            "phone": "01710000101",
            "district": "Dhaka",
            "area": "Dhanmondi",
            "address": "Road 10, House 5, Dhaka",
            "items": [
                {"product_id": prod["id"], "variant_id": by_sku["PH-A-S"]["id"], "quantity": 1},
                {"product_id": prod["id"], "variant_id": by_sku["PH-A-L"]["id"], "quantity": 1},
            ],
        },
    )
    assert online_res.status_code == 201, online_res.text
    order_id = uuid.UUID(online_res.json()["id"])
    order_items = list(
        (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))).all()
    )
    costs_by_sku = {item.sku: item.unit_cost for item in order_items}
    assert costs_by_sku["PH-A-S"] == Decimal("350.50")
    assert costs_by_sku["PH-A-L"] == Decimal("500.00")

    # Purchase against variant PH-A-S updates variant.cost_price via weighted average:
    # Remaining stock of PH-A-S after selling 1 is 9 @ 350.50.
    # Incoming 3 @ 450.50 -> (9*350.50 + 3*450.50) / 12 = (3154.50 + 1351.50)/12 = 375.50.
    purchase_res = await client.post(
        f"{ADMIN_INVENTORY}/purchases",
        headers=auth_headers,
        json={
            "supplier_id": sup_a["id"],
            "purchased_on": "2026-11-15",
            "invoice_no": "INV-VAR-1",
            "items": [
                {
                    "product_id": prod["id"],
                    "variant_id": by_sku["PH-A-S"]["id"],
                    "quantity": 3,
                    "unit_cost": "450.50",
                }
            ],
        },
    )
    assert purchase_res.status_code == 201, purchase_res.text
    db_session.expire_all()
    refreshed_s = await db_session.get(ProductVariant, uuid.UUID(by_sku["PH-A-S"]["id"]))
    assert refreshed_s is not None
    assert refreshed_s.cost_price == Decimal("375.50")
    assert refreshed_s.quantity == 12

    # PATCH product can update supplier to sup_b and then clear it to null,
    # and omitting cost_price on existing variant edit preserves cost_price.
    patch_swap = await client.patch(
        f"{ADMIN_PRODUCTS}/{prod['id']}",
        headers=auth_headers,
        data={"payload": json.dumps({"supplier_id": sup_b["id"]})},
    )
    assert patch_swap.status_code == 200, patch_swap.text
    assert patch_swap.json()["supplier_id"] == sup_b["id"]
    assert patch_swap.json()["supplier_name"] == "Beta Gadgets"

    patch_clear = await client.patch(
        f"{ADMIN_PRODUCTS}/{prod['id']}",
        headers=auth_headers,
        data={"payload": json.dumps({"supplier_id": None})},
    )
    assert patch_clear.status_code == 200, patch_clear.text
    assert patch_clear.json()["supplier_id"] is None
    assert patch_clear.json()["supplier_name"] is None
    assert patch_clear.json()["supplier"] is None


async def test_offline_order_delivered_sync_customer_link_payments_and_reports(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # 1. Register a customer so phone auto-linking can be verified.
    cust_phone = "01755556666"
    reg = await client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Counter Customer",
            "phone": cust_phone,
            "password": "StrongPassword123!",
        },
    )
    assert reg.status_code == 201, reg.text
    cust_token = reg.json()["access_token"]
    cust_headers = {"Authorization": f"Bearer {cust_token}"}

    prod = await _create_product(
        client,
        auth_headers,
        title="Counter Watch",
        price=1000,
        quantity=20,
        cost_price="600.00",
    )

    # 2. Create a backdated walk-in offline order marked immediately delivered.
    walkin_res = await client.post(
        f"{ADMIN_ORDERS}/offline",
        headers={**auth_headers, "Idempotency-Key": f"walkin-{secrets.token_hex(6)}"},
        json={
            "customer_name": "Counter Customer",
            "phone": cust_phone,
            "district": "Dhaka",
            "area": "Dhanmondi",
            "address": "Counter Sale, Dhanmondi, Dhaka",
            "items": [{"product_id": prod["id"], "quantity": 2, "unit_price": 1000}],
            "manual_discount": 150,
            "delivery_charge": 0,
            "payment_method": "due",
            "paid_amount": 500,
            "order_date": "2026-11-05",
            "mark_delivered": True,
        },
    )
    assert walkin_res.status_code == 201, walkin_res.text
    walkin = walkin_res.json()
    assert walkin["status"] == "delivered"
    assert walkin["anonymous"] is False  # linked to registered customer
    assert walkin["total"] == 1850
    assert walkin["paid_amount"] == 500
    assert walkin["due_amount"] == 1350
    assert walkin["payment_status"] == "partial"
    assert walkin["delivered_at"] is not None
    assert walkin["delivered_at"] == walkin["ordered_at"]

    # Customer immediately sees the offline order in their account & purchased products!
    cust_orders = await client.get("/api/v1/customer/orders", headers=cust_headers)
    assert cust_orders.status_code == 200
    assert any(item["number"] == walkin["number"] for item in cust_orders.json()["items"])

    # 3. Record due payment via POST /payments and verify due_amount + activity log.
    overpay = await client.post(
        f"{ADMIN_ORDERS}/{walkin['id']}/payments",
        headers=auth_headers,
        json={"amount": 2000, "payment_method": "cash"},
    )
    assert overpay.status_code == 422

    pay1 = await client.post(
        f"{ADMIN_ORDERS}/{walkin['id']}/payments",
        headers=auth_headers,
        json={
            "amount": 850,
            "payment_method": "bkash",
            "payment_reference": "TRX889900",
            "note": "Second installment",
        },
    )
    assert pay1.status_code == 200, pay1.text
    assert pay1.json()["paid_amount"] == 1350
    assert pay1.json()["due_amount"] == 500
    assert pay1.json()["payment_status"] == "partial"
    assert any(a["action"] == "payment_updated" for a in pay1.json()["activity"])

    # Finish paying the remaining 500 via PATCH paid_amount.
    pay_patch = await client.patch(
        f"{ADMIN_ORDERS}/{walkin['id']}",
        headers=auth_headers,
        json={"paid_amount": 1850},
    )
    assert pay_patch.status_code == 200, pay_patch.text
    assert pay_patch.json()["paid_amount"] == 1850
    assert pay_patch.json()["due_amount"] == 0
    assert pay_patch.json()["payment_status"] == "paid"

    # 4. Backdated offline order starts as `new` and transitions to `delivered` later:
    #    delivered_at preserves ordered_at (2026-11-05) so reports land on exact business date.
    later_res = await client.post(
        f"{ADMIN_ORDERS}/offline",
        headers={**auth_headers, "Idempotency-Key": f"later-{secrets.token_hex(6)}"},
        json={
            "customer_name": "Later Delivered",
            "phone": "01744445555",
            "district": "Dhaka",
            "area": "Dhanmondi",
            "address": "House 99, Road 1, Dhaka",
            "items": [{"product_id": prod["id"], "quantity": 1, "unit_price": 1000}],
            "manual_discount": 100,
            "delivery_charge": 0,
            "payment_method": "cash",
            "paid_amount": 900,
            "order_date": "2026-11-05",
            "initial_status": "new",
        },
    )
    assert later_res.status_code == 201, later_res.text
    later_id = later_res.json()["id"]
    for st in ("confirmed", "packed", "shipped", "delivered"):
        mv = await client.patch(
            f"{ADMIN_ORDERS}/{later_id}", headers=auth_headers, json={"status": st}
        )
        assert mv.status_code == 200, mv.text
    later_row = await db_session.get(Order, uuid.UUID(later_id))
    assert later_row is not None
    assert later_row.delivered_at == later_row.ordered_at

    # 5. Create a third offline order on 2026-11-05, deliver it, then RETURN it.
    ret_res = await client.post(
        f"{ADMIN_ORDERS}/offline",
        headers={**auth_headers, "Idempotency-Key": f"ret-{secrets.token_hex(6)}"},
        json={
            "customer_name": "Returned Buyer",
            "phone": "01733334444",
            "district": "Dhaka",
            "area": "Dhanmondi",
            "address": "House 12, Road 2, Dhaka",
            "items": [{"product_id": prod["id"], "quantity": 1, "unit_price": 1000}],
            "manual_discount": 50,
            "delivery_charge": 60,
            "payment_method": "cash",
            "paid_amount": 1010,
            "order_date": "2026-11-05",
            "initial_status": "delivered",
        },
    )
    assert ret_res.status_code == 201, ret_res.text
    ret_id = ret_res.json()["id"]
    ret_move = await client.patch(
        f"{ADMIN_ORDERS}/{ret_id}", headers=auth_headers, json={"status": "returned"}
    )
    assert ret_move.status_code == 200, ret_move.text
    # Recording a payment on a returned order is rejected.
    ret_pay = await client.post(
        f"{ADMIN_ORDERS}/{ret_id}/payments", headers=auth_headers, json={"amount": 10}
    )
    assert ret_pay.status_code == 422

    # 6. Verify 2026-11-05 reports:
    #    - Walkin (2 units, 2000 gross, 150 manual_discount -> 1850 net, 1200 COGS)
    #    - Later  (1 unit, 1000 gross, 100 manual_discount -> 900 net, 600 COGS)
    #    - Returned order MUST BE EXCLUDED from realized sales/profit/products/trend!
    params = {"from": "2026-11-05", "to": "2026-11-05"}
    sales = await client.get("/api/v1/admin/reports/sales", headers=auth_headers, params=params)
    assert sales.status_code == 200, sales.text
    s = sales.json()
    assert s["order_count"] == 2
    assert s["units_sold"] == 3
    assert s["gross_sales"] == 3000
    assert s["discount"] == 250
    assert s["coupon_discount"] == 0
    assert s["manual_discount"] == 250
    assert s["delivery_charge"] == 0
    assert s["net_sales"] == 2750

    profit = await client.get("/api/v1/admin/reports/profit", headers=auth_headers, params=params)
    assert profit.status_code == 200, profit.text
    p = profit.json()
    assert p["revenue"] == 2750
    assert p["cost"] == 1800.0
    assert p["profit"] == 950.0

    trend = await client.get(
        "/api/v1/admin/reports/trend",
        headers=auth_headers,
        params={"from": "2026-11-05", "to": "2026-11-05", "grain": "day"},
    )
    assert trend.status_code == 200, trend.text
    assert trend.json()["points"][0]["net_sales"] == 2750
    assert trend.json()["points"][0]["profit"] == 950.0

    prod_rep = await client.get(
        "/api/v1/admin/reports/products", headers=auth_headers, params=params
    )
    assert prod_rep.status_code == 200, prod_rep.text
    row = next(item for item in prod_rep.json()["items"] if item["product_id"] == prod["id"])
    assert row["units_sold"] == 3
    assert row["revenue"] == 2750
    assert row["cost"] == 1800.0
    assert row["profit"] == 950.0

    # Delivery report (covering today when returned_at happened) still tracks return count & value.
    today_iso = datetime.now(UTC).date().isoformat()
    today_delivery = await client.get(
        "/api/v1/admin/reports/delivery",
        headers=auth_headers,
        params={"from": "2026-11-05", "to": max("2026-11-25", today_iso)},
    )
    assert today_delivery.status_code == 200, today_delivery.text
    flow = today_delivery.json()
    assert flow["delivered"] == 3
    assert flow["returned"] == 1
    assert flow["returned_value"] == 1010
