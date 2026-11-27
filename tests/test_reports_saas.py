"""Phase B SaaS reporting APIs: P&L, enriched products, channels, suppliers, stock, analytics."""

import json
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Any

from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.services.report_service import window_bounds
from app.services.shop_sql import SHOP
from tests.test_orders import SHIPPING, _key, _move

ADMIN_PRODUCTS = "/api/v1/admin/products"
ADMIN_ORDERS = "/api/v1/admin/orders"
ADMIN_INVENTORY = "/api/v1/admin/inventory"
ADMIN_REPORTS = "/api/v1/admin/reports"


def test_new_report_presets_dhaka_calendar() -> None:
    moment = datetime(2026, 11, 10, 15, 0, tzinfo=SHOP)

    _p, start, end, _o, _c = window_bounds(
        preset="today", date_from=None, date_to=None, now=moment
    )
    assert (start, end) == (date(2026, 11, 10), date(2026, 11, 10))

    _p, start, end, _o, _c = window_bounds(preset="7d", date_from=None, date_to=None, now=moment)
    assert (start, end) == (date(2026, 11, 4), date(2026, 11, 10))

    _p, start, end, _o, _c = window_bounds(
        preset="this_year", date_from=None, date_to=None, now=moment
    )
    assert (start, end) == (date(2026, 1, 1), date(2026, 11, 10))


async def _create_supplier(
    client: AsyncClient, auth_headers: dict[str, str], name: str
) -> dict[str, Any]:
    res = await client.post(
        f"{ADMIN_INVENTORY}/suppliers",
        headers=auth_headers,
        json={"name": name, "phone": "01711110000", "address": "Dhaka", "note": ""},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_product(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    title: str,
    price: int,
    compare_at_price: int | None = None,
    quantity: int = 20,
    cost_price: str | None = None,
    supplier_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "category": "gadgets",
        "price": price,
        "quantity": quantity,
        "weight_grams": 500,
        "published": True,
        "image_src": "/uploads/saas-report.png",
    }
    if compare_at_price is not None:
        payload["compare_at_price"] = compare_at_price
    if cost_price is not None:
        payload["cost_price"] = cost_price
    if supplier_id is not None:
        payload["supplier_id"] = supplier_id
    res = await client.post(
        ADMIN_PRODUCTS,
        headers=auth_headers,
        data={"payload": json.dumps(payload)},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _place_online(
    client: AsyncClient,
    product_id: str,
    quantity: int,
    *,
    phone: str = "01710000001",
    payment_method: str = "cod",
    advance_percent: int | None = None,
    coupon_code: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "direct",
        "items": [{"product_id": product_id, "quantity": quantity}],
        **SHIPPING,
        "phone": phone,
        "payment_method": payment_method,
    }
    if advance_percent is not None:
        body["advance_percent"] = advance_percent
        body["payment_reference"] = "QR123456"
    if coupon_code is not None:
        body["coupon_code"] = coupon_code
    res = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=body,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _deliver(client: AsyncClient, headers: dict[str, str], order_id: str) -> None:
    for status in ("confirmed", "packed", "shipped", "delivered"):
        moved = await _move(client, headers, order_id, status)
        assert moved.status_code == 200, moved.text


async def _stamp(db: AsyncSession, order_id: str, **values: object) -> None:
    await db.execute(update(Order).where(Order.id == uuid.UUID(order_id)).values(**values))
    await db.commit()


async def _create_offline(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    items: list[dict[str, Any]],
    order_date: str,
    payment_method: str = "cash",
    paid_amount: int = 0,
    manual_discount: int = 0,
    delivery_charge: int = 0,
    initial_status: str = "delivered",
    phone: str = "01810000001",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "customer_name": "Walk-in Customer",
        "phone": phone,
        "district": "Dhaka",
        "area": "Dhanmondi",
        "address": "House 12, Road 4",
        "payment_method": payment_method,
        "paid_amount": paid_amount,
        "manual_discount": manual_discount,
        "delivery_charge": delivery_charge,
        "order_date": order_date,
        "initial_status": initial_status,
        "items": items,
    }
    res = await client.post(
        f"{ADMIN_ORDERS}/offline",
        headers={**auth_headers, "Idempotency-Key": f"off-{secrets.token_hex(6)}"},
        json=body,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_phase_b_saas_reports_and_exports(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # 1. Create suppliers & products: profitable, loss-making, unknown-cost
    sup_alpha = await _create_supplier(client, auth_headers, "Alpha Distributors")
    sup_beta = await _create_supplier(client, auth_headers, "Beta Imports")

    profitable = await _create_product(
        client,
        auth_headers,
        title="Pro Earbuds",
        price=1000,
        compare_at_price=1200,
        quantity=10,
        cost_price="600.00",
        supplier_id=sup_alpha["id"],
    )
    loss_item = await _create_product(
        client,
        auth_headers,
        title="Clearance Charger",
        price=300,
        quantity=8,
        cost_price="450.00",
        supplier_id=sup_beta["id"],
    )
    unknown_item = await _create_product(
        client,
        auth_headers,
        title="Mystery Cable",
        price=250,
        quantity=5,
        cost_price=None,
        supplier_id=sup_alpha["id"],
    )

    # Record a purchase for sup_alpha on 2026-11-09 (5 units @ 600 = 3000)
    purch = await client.post(
        f"{ADMIN_INVENTORY}/purchases",
        headers=auth_headers,
        json={
            "supplier_id": sup_alpha["id"],
            "purchased_on": "2026-11-09",
            "invoice_no": "INV-900",
            "note": "Restock",
            "items": [
                {"product_id": profitable["id"], "quantity": 5, "unit_cost": "600.00"}
            ],
        },
    )
    assert purch.status_code == 201, purch.text

    # 2. Online COD order (delivered on 2026-11-09): 2x Pro Earbuds @ 1000 (list 1200)
    online_cod = await _place_online(
        client, profitable["id"], 2, phone="01710000011", payment_method="cod"
    )
    await _deliver(client, auth_headers, online_cod["id"])
    await _stamp(
        db_session,
        online_cod["id"],
        delivered_at=datetime(2026, 11, 9, 5, 0, tzinfo=UTC),
    )

    # 3. Online returned order (returned on 2026-11-09): 1x Pro Earbuds
    online_ret = await _place_online(
        client, profitable["id"], 1, phone="01710000012", payment_method="cod"
    )
    await _deliver(client, auth_headers, online_ret["id"])
    ret_res = await _move(client, auth_headers, online_ret["id"], "returned")
    assert ret_res.status_code == 200, ret_res.text
    await _stamp(
        db_session,
        online_ret["id"],
        delivered_at=datetime(2026, 11, 9, 4, 0, tzinfo=UTC),
        returned_at=datetime(2026, 11, 9, 7, 0, tzinfo=UTC),
    )

    # 4. Offline cash order on 2026-11-09 (delivered immediately):
    #    1x Clearance Charger @ 300 (cost 450) + manual_discount 50 -> net 250, loss 200
    offline_loss = await _create_offline(
        client,
        auth_headers,
        items=[{"product_id": loss_item["id"], "quantity": 1, "unit_price": 300}],
        order_date="2026-11-09",
        payment_method="cash",
        paid_amount=250,
        manual_discount=50,
        delivery_charge=0,
        initial_status="delivered",
    )
    assert offline_loss["total"] == 250

    # 5. Offline DUE order on 2026-11-09 (delivered immediately, partial payment 100, due 150):
    #    1x Mystery Cable @ 250 (unknown cost)
    offline_due = await _create_offline(
        client,
        auth_headers,
        items=[{"product_id": unknown_item["id"], "quantity": 1, "unit_price": 250}],
        order_date="2026-11-09",
        payment_method="due",
        paid_amount=100,
        manual_discount=0,
        delivery_charge=0,
        initial_status="delivered",
    )
    assert offline_due["total"] == 250

    cod_merch = online_cod["items"][0]["line_total"]
    cod_reg = online_cod["items"][0]["regular_price"] or online_cod["items"][0]["unit_price"]
    cod_gross = cod_reg * 2
    cod_profit = round(cod_merch - 1200.0, 2)
    known_rev = cod_merch + 250
    total_profit = round(known_rev - 1650.0, 2)

    params = {"from": "2026-11-09", "to": "2026-11-09"}

    # --- A. Profit & Loss Summary (/profit-loss) ---
    pnl_res = await client.get(
        f"{ADMIN_REPORTS}/profit-loss", headers=auth_headers, params=params
    )
    assert pnl_res.status_code == 200, pnl_res.text
    pnl = pnl_res.json()
    assert pnl["gross_sales"] == cod_gross + 300 + 250
    assert pnl["product_discount"] == cod_gross - cod_merch
    assert pnl["coupon_discount"] == 0
    assert pnl["manual_discount"] == 50
    assert pnl["delivery_charge"] == online_cod["shipping"]
    assert pnl["returned_order_value"] == online_ret["total"]
    assert pnl["net_realized_sales"] == (cod_merch + 300 + 250) + online_cod["shipping"] - 50
    assert pnl["total_cost"] == 1650.0
    assert pnl["gross_profit"] == total_profit
    # Loss line: Clearance Charger net 250 - cost 450 = -200 -> loss_amount = 200.0
    assert pnl["loss_amount"] == 200.0
    assert pnl["net_profit"] == total_profit
    assert pnl["margin_percent"] == round(total_profit * 100.0 / known_rev, 2)
    # Collections: online_cod (settled COD) + offline_loss (paid 250) + offline_due (paid 100)
    assert pnl["collected_amount"] == online_cod["total"] + 250 + 100
    assert pnl["due_amount"] == 150
    assert pnl["unknown_cost_lines"] == 1
    assert pnl["unknown_cost_units"] == 1
    assert pnl["unknown_cost_revenue"] == 250

    # Upgraded /profit also exposes loss_amount and net_profit
    prof_res = await client.get(f"{ADMIN_REPORTS}/profit", headers=auth_headers, params=params)
    assert prof_res.status_code == 200, prof_res.text
    prof = prof_res.json()
    assert prof["loss_amount"] == 200.0
    assert prof["net_profit"] == total_profit

    # --- B. Upgraded Product Report (/products) ---
    prod_res = await client.get(
        f"{ADMIN_REPORTS}/products",
        headers=auth_headers,
        params={**params, "sort": "profit"},
    )
    assert prod_res.status_code == 200, prod_res.text
    prod_body = prod_res.json()
    assert prod_body["sort"] == "profit"
    items_by_title = {row["title"]: row for row in prod_body["items"]}
    assert set(items_by_title) == {"Pro Earbuds", "Clearance Charger", "Mystery Cable"}

    earbuds = items_by_title["Pro Earbuds"]
    assert earbuds["slug"] == profitable["slug"]
    assert earbuds["category_name"] != ""
    assert earbuds["supplier_id"] == sup_alpha["id"]
    assert earbuds["supplier_name"] == "Alpha Distributors"
    assert earbuds["units_sold"] == 2
    assert earbuds["avg_selling_price"] == round(cod_merch / 2, 2)
    assert earbuds["unit_cost_avg"] == 600.0
    assert earbuds["current_cost_price"] == 600.0
    # Started at 10, +5 purchased, -2 sold, -1 sold & +1 returned = 13
    assert earbuds["current_stock"] == 13
    assert earbuds["stock_value"] == 13 * 600.0
    assert earbuds["profit"] == cod_profit
    assert earbuds["is_loss"] is False
    assert earbuds["return_count"] == 1
    assert earbuds["returned_units"] == 1

    charger = items_by_title["Clearance Charger"]
    assert charger["profit"] == -200.0
    assert charger["is_loss"] is True

    # Profit DESC NULLS LAST: Pro Earbuds (>0), Clearance Charger (-200), Mystery Cable (None)
    assert [row["title"] for row in prod_body["items"]] == [
        "Pro Earbuds",
        "Clearance Charger",
        "Mystery Cable",
    ]

    # Profit filters: profit / loss / unknown_cost
    only_loss = await client.get(
        f"{ADMIN_REPORTS}/products",
        headers=auth_headers,
        params={**params, "profit_filter": "loss"},
    )
    assert only_loss.status_code == 200, only_loss.text
    assert [r["title"] for r in only_loss.json()["items"]] == ["Clearance Charger"]

    only_profit = await client.get(
        f"{ADMIN_REPORTS}/products",
        headers=auth_headers,
        params={**params, "profit_filter": "profit"},
    )
    assert [r["title"] for r in only_profit.json()["items"]] == ["Pro Earbuds"]

    only_unknown = await client.get(
        f"{ADMIN_REPORTS}/products",
        headers=auth_headers,
        params={**params, "profit_filter": "unknown_cost"},
    )
    assert [r["title"] for r in only_unknown.json()["items"]] == ["Mystery Cable"]

    # Filter by supplier_id and origin
    alpha_only = await client.get(
        f"{ADMIN_REPORTS}/products",
        headers=auth_headers,
        params={**params, "supplier_id": sup_alpha["id"]},
    )
    assert {r["title"] for r in alpha_only.json()["items"]} == {"Pro Earbuds", "Mystery Cable"}

    offline_only = await client.get(
        f"{ADMIN_REPORTS}/products",
        headers=auth_headers,
        params={**params, "origin": "offline"},
    )
    assert {r["title"] for r in offline_only.json()["items"]} == {
        "Clearance Charger",
        "Mystery Cable",
    }

    # --- C. Channel & Payment Breakdown (/channels) ---
    ch_res = await client.get(f"{ADMIN_REPORTS}/channels", headers=auth_headers, params=params)
    assert ch_res.status_code == 200, ch_res.text
    ch_body = ch_res.json()
    by_origin = {row["origin"]: row for row in ch_body["channels"]}
    assert by_origin["online"]["order_count"] == 1
    assert by_origin["online"]["units"] == 2
    assert by_origin["online"]["net_sales"] == online_cod["total"]
    assert by_origin["online"]["cogs"] == 1200.0
    assert by_origin["online"]["profit"] == cod_profit
    assert by_origin["online"]["collected"] == online_cod["total"]
    assert by_origin["online"]["due"] == 0

    assert by_origin["offline"]["order_count"] == 2
    assert by_origin["offline"]["units"] == 2
    assert by_origin["offline"]["net_sales"] == 500
    assert by_origin["offline"]["cogs"] == 450.0
    assert by_origin["offline"]["profit"] == -200.0
    assert by_origin["offline"]["collected"] == 350
    assert by_origin["offline"]["due"] == 150

    by_pm = {row["payment_method"]: row for row in ch_body["payment_methods"]}
    assert by_pm["cod"]["order_count"] == 1
    assert by_pm["cod"]["collected"] == online_cod["total"]
    assert by_pm["cash"]["order_count"] == 1
    assert by_pm["cash"]["collected"] == 250
    assert by_pm["cash"]["due"] == 0
    assert by_pm["due"]["order_count"] == 1
    assert by_pm["due"]["collected"] == 100
    assert by_pm["due"]["due"] == 150
    assert by_pm["due"]["cogs"] is None
    assert by_pm["due"]["unknown_cost_units"] == 1

    # --- D. Supplier Performance Report (/suppliers) ---
    sup_res = await client.get(f"{ADMIN_REPORTS}/suppliers", headers=auth_headers, params=params)
    assert sup_res.status_code == 200, sup_res.text
    sup_body = sup_res.json()
    by_sup = {row["supplier_name"]: row for row in sup_body["items"]}
    alpha_row = by_sup["Alpha Distributors"]
    assert alpha_row["linked_products_count"] == 2
    assert alpha_row["purchase_count"] == 1
    assert alpha_row["total_purchased_units"] == 5
    assert alpha_row["total_purchase_spend"] == 3000.0
    assert alpha_row["units_sold"] == 3  # 2 earbuds + 1 mystery cable
    assert alpha_row["sales_revenue"] == cod_merch + 250
    assert alpha_row["cogs"] == 1200.0
    assert alpha_row["net_profit"] == cod_profit
    assert alpha_row["current_stock_units"] == 13 + 4  # 13 earbuds + 4 cables
    assert alpha_row["current_stock_value"] == 13 * 600.0

    beta_row = by_sup["Beta Imports"]
    assert beta_row["linked_products_count"] == 1
    assert beta_row["purchase_count"] == 0
    assert beta_row["units_sold"] == 1
    assert beta_row["sales_revenue"] == 250
    assert beta_row["cogs"] == 450.0
    assert beta_row["net_profit"] == -200.0
    assert beta_row["current_stock_units"] == 7
    assert beta_row["current_stock_value"] == 7 * 450.0

    assert sup_body["total_purchase_spend"] == 3000.0
    assert sup_body["total_sales_revenue"] == cod_merch + 500
    assert sup_body["total_cogs"] == 1650.0
    assert sup_body["total_net_profit"] == total_profit

    # --- E. Upgraded Stock Report (/stock) ---
    stock_res = await client.get(
        f"{ADMIN_REPORTS}/stock",
        headers=auth_headers,
        params={**params, "supplier_id": sup_alpha["id"]},
    )
    assert stock_res.status_code == 200, stock_res.text
    stock = stock_res.json()
    assert stock["summary"]["product_count"] == 2
    assert stock["summary"]["missing_cost_count"] == 1
    # Pro Earbuds: 13 * 1000 = 13000 retail, 13 * 600 = 7800 cost -> 5200 expected profit
    # Mystery Cable: 4 * 250 = 1000 retail, cost None
    assert stock["summary"]["potential_retail_value"] == 14000.0
    assert stock["summary"]["expected_profit_on_hand"] == 5200.0
    stock_by_title = {row["title"]: row for row in stock["items"]}
    assert stock_by_title["Pro Earbuds"]["selling_price"] == 1000
    assert stock_by_title["Pro Earbuds"]["potential_retail_value"] == 13000.0
    assert stock_by_title["Pro Earbuds"]["expected_profit_on_hand"] == 5200.0
    assert stock_by_title["Pro Earbuds"]["supplier_name"] == "Alpha Distributors"
    assert stock_by_title["Mystery Cable"]["expected_profit_on_hand"] is None

    # --- F. Excel (.xlsx) Exports for profit-loss, channels, suppliers ---
    for endpoint, expected_header in (
        ("profit-loss", "Gross sales"),
        ("channels", "Breakdown"),
        ("suppliers", "Supplier"),
        ("products", "Avg selling price"),
        ("stock", "Potential retail value"),
    ):
        exp = await client.get(
            f"{ADMIN_REPORTS}/{endpoint}/export", headers=auth_headers, params=params
        )
        assert exp.status_code == 200, f"{endpoint}: {exp.text}"
        assert exp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        wb = load_workbook(BytesIO(exp.content), data_only=True)
        ws = wb.active
        assert ws is not None
        flat = [cell for row in ws.iter_rows(values_only=True) for cell in row]
        assert expected_header in flat, f"Missing {expected_header!r} in {endpoint} export"


async def test_single_product_analytics_endpoint(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    sup = await _create_supplier(client, auth_headers, "Analytics Vendor")
    prod = await _create_product(
        client,
        auth_headers,
        title="Smart Lamp",
        price=800,
        quantity=10,
        cost_price="500.00",
        supplier_id=sup["id"],
    )

    # Order 1: delivered 60 days ago (lifetime only, NOT in last 30 days)
    old_order = await _place_online(client, prod["id"], 2, phone="01720000001")
    await _deliver(client, auth_headers, old_order["id"])
    sixty_days_ago = datetime.now(UTC) - timedelta(days=60)
    await _stamp(db_session, old_order["id"], delivered_at=sixty_days_ago)

    # Order 2: delivered today (both lifetime AND last 30 days)
    recent_order = await _place_online(client, prod["id"], 1, phone="01720000002")
    await _deliver(client, auth_headers, recent_order["id"])

    # Order 3: returned today
    ret_order = await _place_online(client, prod["id"], 1, phone="01720000003")
    await _deliver(client, auth_headers, ret_order["id"])
    ret_move = await _move(client, auth_headers, ret_order["id"], "returned")
    assert ret_move.status_code == 200, ret_move.text

    res = await client.get(f"{ADMIN_PRODUCTS}/{prod['id']}/analytics", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["product_id"] == prod["id"]
    assert body["supplier_id"] == sup["id"]
    assert body["supplier_name"] == "Analytics Vendor"
    assert body["current_stock"] == 7  # 10 - 2 - 1 - 1 + 1
    assert body["current_cost_price"] == 500.0
    assert body["selling_price"] == 800
    assert body["current_stock_value"] == 3500.0
    assert body["potential_retail_value"] == 5600.0

    # Lifetime: 3 units (2 old + 1 recent)
    old_rev = old_order["items"][0]["line_total"]
    recent_rev = recent_order["items"][0]["line_total"]
    life_rev = old_rev + recent_rev
    life_profit = round(life_rev - 1500.0, 2)
    assert body["lifetime"]["units_sold"] == 3
    assert body["lifetime"]["revenue"] == life_rev
    assert body["lifetime"]["cogs"] == 1500.0
    assert body["lifetime"]["profit"] == life_profit
    assert body["lifetime"]["is_loss"] is False
    assert body["lifetime"]["margin_percent"] == round(life_profit * 100.0 / life_rev, 2)
    assert body["lifetime"]["return_count"] == 1
    assert body["lifetime"]["returned_units"] == 1

    # Last 30 days: 1 unit
    assert body["last_30_days"]["units_sold"] == 1
    assert body["last_30_days"]["revenue"] == recent_rev
    assert body["last_30_days"]["cogs"] == 500.0
    assert body["last_30_days"]["profit"] == round(recent_rev - 500.0, 2)
    assert body["last_30_days"]["return_count"] == 1

    # Recent movements present (3 sales + 1 return = 4 movements)
    assert len(body["recent_movements"]) >= 4
    types = {m["movement_type"] for m in body["recent_movements"]}
    assert "sale" in types
    assert "return" in types

    # 404 on missing product
    missing = await client.get(
        f"{ADMIN_PRODUCTS}/{uuid.uuid4()}/analytics", headers=auth_headers
    )
    assert missing.status_code == 404


async def test_phase_b_filters_sorts_presets_and_empty_window(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Empty window returns clean zero totals without division errors.
    empty_pnl = await client.get(
        f"{ADMIN_REPORTS}/profit-loss",
        headers=auth_headers,
        params={"from": "2026-01-01", "to": "2026-01-02"},
    )
    assert empty_pnl.status_code == 200, empty_pnl.text
    pnl = empty_pnl.json()
    assert pnl["gross_sales"] == 0
    assert pnl["total_cost"] == 0.0
    assert pnl["gross_profit"] == 0.0
    assert pnl["loss_amount"] == 0.0
    assert pnl["net_profit"] == 0.0
    assert pnl["margin_percent"] is None
    assert pnl["collected_amount"] == 0
    assert pnl["due_amount"] == 0

    # All new presets work via HTTP
    for preset in ("today", "7d", "this_year"):
        res = await client.get(
            f"{ADMIN_REPORTS}/profit-loss",
            headers=auth_headers,
            params={"preset": preset},
        )
        assert res.status_code == 200, f"{preset}: {res.text}"
        assert res.json()["filters"]["preset"] == preset

    # All product sort options & profit_filter=all work via HTTP
    for sort in ("revenue", "profit", "margin", "units_sold", "cost", "stock_value"):
        res = await client.get(
            f"{ADMIN_REPORTS}/products",
            headers=auth_headers,
            params={"preset": "7d", "sort": sort, "profit_filter": "all"},
        )
        assert res.status_code == 200, f"{sort}: {res.text}"
        assert res.json()["sort"] == sort

    # Invalid supplier_id, origin, profit_filter, and sort return 422
    bad_sup = await client.get(
        f"{ADMIN_REPORTS}/profit-loss",
        headers=auth_headers,
        params={"preset": "today", "supplier_id": str(uuid.uuid4())},
    )
    assert bad_sup.status_code == 422

    bad_origin = await client.get(
        f"{ADMIN_REPORTS}/channels",
        headers=auth_headers,
        params={"preset": "today", "origin": "mobile"},
    )
    assert bad_origin.status_code == 422

    bad_sort = await client.get(
        f"{ADMIN_REPORTS}/products",
        headers=auth_headers,
        params={"preset": "today", "sort": "bogus"},
    )
    assert bad_sort.status_code == 422

    # Anonymous access is rejected (401)
    anon = await client.get(f"{ADMIN_REPORTS}/profit-loss", params={"preset": "today"})
    assert anon.status_code == 401

