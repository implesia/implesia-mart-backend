"""Inventory ledger: weighted cost, order movements, opening stock, Excel, roles."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from httpx import AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import StockMovement
from app.models.order import Order
from app.models.product import Product
from app.services import inventory_service, order_service, pricing_service
from app.services.inventory_excel import (
    COST_COLUMNS,
    OPENING_COLUMNS,
    PURCHASE_COLUMNS,
    STOCK_COUNT_COLUMNS,
)
from tests.test_orders import SHIPPING, _key, _move, _stock
from tests.test_products import _create
from tests.test_variants import _make, _order, _variant

_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_BASE = "/api/v1/admin/inventory"


def test_weighted_average_cost_edges() -> None:
    average = inventory_service.weighted_average_cost
    assert average(10, Decimal("5"), 10, Decimal("7")) == Decimal("6.00")
    assert average(1, Decimal("1.00"), 1, Decimal("1.01")) == Decimal("1.01")
    assert average(5, Decimal("0"), 5, Decimal("10")) == Decimal("5.00")
    assert average(None, None, 2, Decimal("8")) == Decimal("8.00")
    assert average(5, None, 2, Decimal("4")) == Decimal("4.00")
    assert average(0, Decimal("9"), 4, Decimal("3")) == Decimal("3.00")
    assert average(-1, Decimal("9"), 4, Decimal("3")) == Decimal("3.00")
    with pytest.raises(ValueError):
        average(1, Decimal("1"), 0, Decimal("1"))
    with pytest.raises(ValueError):
        average(1, Decimal("1"), 2, Decimal("-1"))


def _sheet(headers: tuple[str, ...] | list[str], rows: list[list[object]]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(list(headers))
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _cells(columns: tuple[str, ...], **values: object) -> list[object]:
    row = dict.fromkeys(columns, "")
    row.update(values)
    return [row[name] for name in columns]


def _upload(name: str, data: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, data, _MIME)}


async def _supplier(
    client: AsyncClient, headers: dict[str, str], name: str = "Karim Traders"
) -> dict:
    response = await client.post(
        f"{_BASE}/suppliers",
        headers=headers,
        json={"name": name, "phone": "01711111111", "address": "Dhaka", "note": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _buy(
    client: AsyncClient,
    headers: dict[str, str],
    supplier_id: str,
    product_id: str,
    quantity: int,
    unit_cost: str,
    variant_id: str | None = None,
) -> dict:
    item: dict[str, object] = {
        "product_id": product_id,
        "quantity": quantity,
        "unit_cost": unit_cost,
    }
    if variant_id is not None:
        item["variant_id"] = variant_id
    response = await client.post(
        f"{_BASE}/purchases",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "purchased_on": "2026-11-01",
            "invoice_no": "INV-1",
            "items": [item],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _movements(
    client: AsyncClient,
    headers: dict[str, str],
    product_id: str,
    movement_type: str | None = None,
) -> list[dict]:
    params: dict[str, str] = {"product_id": product_id, "page_size": "100"}
    if movement_type is not None:
        params["movement_type"] = movement_type
    response = await client.get(f"{_BASE}/movements", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def _preview(
    client: AsyncClient, headers: dict[str, str], kind: str, name: str, data: bytes
):
    return await client.post(
        f"{_BASE}/imports/preview",
        headers=headers,
        data={"import_type": kind},
        files=_upload(name, data),
    )


async def _confirm(
    client: AsyncClient,
    headers: dict[str, str],
    kind: str,
    name: str,
    data: bytes,
    *,
    duplicate: bool = False,
):
    return await client.post(
        f"{_BASE}/imports/confirm",
        headers=headers,
        data={"import_type": kind, "confirm_duplicate": "true" if duplicate else "false"},
        files=_upload(name, data),
    )


async def _staff(
    client: AsyncClient, headers: dict[str, str], email: str, role: str
) -> dict[str, str]:
    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": email,
            "full_name": role,
            "password": "viewer-passphrase",
            "role": role,
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "viewer-passphrase"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _keys(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


async def test_purchase_weighted_average_covers_the_edge_cases(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    supplier = await _supplier(client, auth_headers)

    mixed = await _create(
        client, auth_headers, title="Mixed lamp", price=1000, quantity=10, cost_price="5.00"
    )
    bought = await _buy(client, auth_headers, supplier["id"], mixed["id"], 10, "7")
    assert bought["items"][0]["quantity"] == 10
    assert bought["items"][0]["unit_cost"] == 7
    after = await _stock(client, auth_headers, mixed["id"])
    assert after["quantity"] == 20
    assert after["cost_price"] == 6

    penny = await _create(
        client, auth_headers, title="Penny lamp", price=1000, quantity=1, cost_price="1.00"
    )
    await _buy(client, auth_headers, supplier["id"], penny["id"], 1, "1.01")
    assert (await _stock(client, auth_headers, penny["id"]))["cost_price"] == 1.01
    assert (await _stock(client, auth_headers, penny["id"]))["quantity"] == 2

    empty = await _create(
        client,
        auth_headers,
        title="Empty lamp",
        price=1000,
        quantity=0,
        cost_price="9.00",
        status="sold-out",
    )
    await _buy(client, auth_headers, supplier["id"], empty["id"], 4, "3")
    restocked = await _stock(client, auth_headers, empty["id"])
    assert restocked["quantity"] == 4
    assert restocked["cost_price"] == 3
    assert restocked["status"] == "available"

    missing = await _create(client, auth_headers, title="No cost lamp", price=1000, quantity=5)
    await _buy(client, auth_headers, supplier["id"], missing["id"], 2, "4")
    filled = await _stock(client, auth_headers, missing["id"])
    assert filled["quantity"] == 7
    assert filled["cost_price"] == 4

    made = await _create(client, auth_headers, title="Made lamp", price=1000, quantity=None)
    await _buy(client, auth_headers, supplier["id"], made["id"], 2, "8")
    still = await _stock(client, auth_headers, made["id"])
    assert still["quantity"] is None
    assert still["cost_price"] == 8
    purchase_rows = await _movements(client, auth_headers, made["id"], "purchase")
    assert len(purchase_rows) == 1
    assert purchase_rows[0]["quantity"] == 2
    assert purchase_rows[0]["unit_cost"] == 8

    public = await client.get(f"/api/v1/products/{mixed['id']}")
    assert public.status_code == 200, public.text
    assert "unit_cost" not in set(_keys(public.json()))
    assert "cost_price" not in public.text


async def test_variant_purchase_weighs_that_option_only(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers, title="Bought tee", cost_price="5.00")
    target = _variant(product, "red", "m")
    supplier = await _supplier(client, auth_headers, "Variant Traders")
    await _buy(client, auth_headers, supplier["id"], product["id"], 1, "11", target["id"])
    fresh = await _stock(client, auth_headers, product["id"])
    updated = _variant(fresh, "red", "m")
    untouched = _variant(fresh, "navy", "l")
    assert updated["quantity"] == 4
    assert untouched["quantity"] == 3
    assert fresh["quantity"] == 13
    assert fresh["cost_price"] == 6.5
    rows = await _movements(client, auth_headers, product["id"], "purchase")
    assert len(rows) == 1
    assert rows[0]["variant_id"] == target["id"]
    assert rows[0]["quantity"] == 1


async def test_order_claim_cancel_and_return_write_movements(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(
        client, auth_headers, title="Ledger lamp", price=1000, quantity=8, cost_price="10.00"
    )
    product_id = product["id"]

    cancelled = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product_id, "quantity": 2}],
            **SHIPPING,
        },
    )
    assert cancelled.status_code == 201, cancelled.text
    assert (await _stock(client, auth_headers, product_id))["quantity"] == 6
    sales = await _movements(client, auth_headers, product_id, "sale")
    assert len(sales) == 1
    assert sales[0]["quantity"] == -2
    assert sales[0]["unit_cost"] == 10
    assert sales[0]["order_id"] == cancelled.json()["id"]
    moved = await _move(client, auth_headers, cancelled.json()["id"], "cancelled")
    assert moved.status_code == 200
    assert (await _stock(client, auth_headers, product_id))["quantity"] == 8
    cancels = await _movements(client, auth_headers, product_id, "cancel")
    assert len(cancels) == 1
    assert cancels[0]["quantity"] == 2
    assert cancels[0]["order_id"] == cancelled.json()["id"]
    blocked = await _move(client, auth_headers, cancelled.json()["id"], "confirmed")
    assert blocked.status_code == 409
    assert len(await _movements(client, auth_headers, product_id, "cancel")) == 1
    assert (await _stock(client, auth_headers, product_id))["quantity"] == 8

    returned = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product_id, "quantity": 1}],
            **SHIPPING,
        },
    )
    assert returned.status_code == 201, returned.text
    for status in ("confirmed", "packed", "shipped", "returned"):
        assert (await _move(client, auth_headers, returned.json()["id"], status)).status_code == 200
    assert (await _stock(client, auth_headers, product_id))["quantity"] == 8
    returns = await _movements(client, auth_headers, product_id, "return")
    assert len(returns) == 1
    assert returns[0]["quantity"] == 1
    assert returns[0]["order_id"] == returned.json()["id"]

    delivered = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product_id, "quantity": 1}],
            **SHIPPING,
        },
    )
    assert delivered.status_code == 201, delivered.text
    for status in ("confirmed", "packed", "shipped", "delivered"):
        delivered_move = await _move(client, auth_headers, delivered.json()["id"], status)
        assert delivered_move.status_code == 200
    assert (await _stock(client, auth_headers, product_id))["quantity"] == 7
    assert len(await _movements(client, auth_headers, product_id, "return")) == 1
    assert len(await _movements(client, auth_headers, product_id, "sale")) == 3

    oversell = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product_id, "quantity": 100}],
            **SHIPPING,
        },
    )
    assert oversell.status_code == 422
    assert (await _stock(client, auth_headers, product_id))["quantity"] == 7
    assert len(await _movements(client, auth_headers, product_id)) == 5

    lookup = await client.post(
        "/api/v1/orders/lookup",
        json={"number": delivered.json()["number"], "phone": SHIPPING["phone"]},
    )
    assert lookup.status_code == 200, lookup.text
    assert "unit_cost" not in set(_keys(lookup.json()))


async def test_variant_order_writes_the_sale_on_that_option(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers, title="Sold tee", cost_price="4.00")
    target = _variant(product, "red", "m")
    placed = await _order(
        client, [{"product_id": product["id"], "variant_id": target["id"], "quantity": 1}]
    )
    assert placed.status_code == 201, placed.text
    fresh = await _stock(client, auth_headers, product["id"])
    assert _variant(fresh, "red", "m")["quantity"] == 2
    assert fresh["quantity"] == 11
    sales = await _movements(client, auth_headers, product["id"], "sale")
    assert len(sales) == 1
    assert sales[0]["variant_id"] == target["id"]
    assert sales[0]["quantity"] == -1
    assert sales[0]["unit_cost"] == 4
    assert (await _move(client, auth_headers, placed.json()["id"], "cancelled")).status_code == 200
    restored = await _stock(client, auth_headers, product["id"])
    assert _variant(restored, "red", "m")["quantity"] == 3
    assert restored["quantity"] == 12
    cancels = await _movements(client, auth_headers, product["id"], "cancel")
    assert len(cancels) == 1
    assert cancels[0]["quantity"] == 1
    assert cancels[0]["variant_id"] == target["id"]


async def test_sale_movement_rolls_back_with_the_stock(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    created = await _create(
        client, auth_headers, title="Rollback lamp", price=1000, quantity=4, cost_price="2.50"
    )
    product = await db_session.get(Product, uuid.UUID(created["id"]))
    assert product is not None
    rules = await pricing_service.store_rules(db_session)
    await order_service._claim(db_session, product, None, 1, rules)
    order = Order(
        id=uuid.uuid4(),
        number="IM-ROLLBACK1",
        source="direct",
        status="new",
        payment_method="cod",
        customer_name="Rina",
        phone="01700000000",
        district="Dhaka",
        area="Gulshan",
        address="House 1",
        delivery_zone="inside",
        subtotal=1000,
        shipping=0,
        total=1000,
    )
    db_session.add(order)
    await db_session.flush()
    inventory_service.attach_pending_sales(db_session, order.id)
    await db_session.flush()
    staged = await db_session.scalar(select(func.count()).select_from(StockMovement))
    assert staged == 1
    await db_session.rollback()
    fresh = await db_session.get(Product, uuid.UUID(created["id"]), populate_existing=True)
    assert fresh is not None
    assert fresh.quantity == 4
    left = await db_session.scalar(select(func.count()).select_from(StockMovement))
    assert left == 0


async def test_opening_stock_is_idempotent_and_does_not_change_the_count(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    plain = await _create(client, auth_headers, title="Opening lamp", price=500, quantity=7)
    await _create(client, auth_headers, title="Made to order", price=500, quantity=None)
    variant_product = await _make(client, auth_headers, title="Opening tee")

    first = await client.post(f"{_BASE}/opening-stock", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json() == {"created": 5, "already_recorded": 0, "untracked": 1}
    assert (await _stock(client, auth_headers, plain["id"]))["quantity"] == 7
    assert (await _stock(client, auth_headers, variant_product["id"]))["quantity"] == 12
    openings = await _movements(client, auth_headers, plain["id"], "opening")
    assert len(openings) == 1
    assert openings[0]["quantity"] == 7
    assert openings[0]["variant_id"] is None
    variant_rows = await _movements(client, auth_headers, variant_product["id"], "opening")
    assert len(variant_rows) == 4
    assert all(row["variant_id"] is not None for row in variant_rows)
    assert {row["quantity"] for row in variant_rows} == {3}

    second = await client.post(f"{_BASE}/opening-stock", headers=auth_headers)
    assert second.status_code == 200, second.text
    assert second.json() == {"created": 0, "already_recorded": 5, "untracked": 1}
    assert len(await _movements(client, auth_headers, plain["id"], "opening")) == 1
    assert (await _stock(client, auth_headers, plain["id"]))["quantity"] == 7


async def test_adjustment_requires_a_reason_and_cannot_go_negative(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Counted lamp", price=500, quantity=5)
    missing = await client.post(
        f"{_BASE}/adjustments",
        headers=auth_headers,
        json={"product_id": product["id"], "quantity": -1},
    )
    assert missing.status_code == 422
    blank = await client.post(
        f"{_BASE}/adjustments",
        headers=auth_headers,
        json={"product_id": product["id"], "quantity": -1, "reason": "   "},
    )
    assert blank.status_code == 422
    too_many = await client.post(
        f"{_BASE}/adjustments",
        headers=auth_headers,
        json={"product_id": product["id"], "quantity": -9, "reason": "Lost"},
    )
    assert too_many.status_code == 422
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 5
    damaged = await client.post(
        f"{_BASE}/adjustments",
        headers=auth_headers,
        json={"product_id": product["id"], "quantity": -2, "reason": "Damaged"},
    )
    assert damaged.status_code == 201, damaged.text
    assert damaged.json()["movement_type"] == "adjustment"
    assert damaged.json()["quantity"] == -2
    assert damaged.json()["note"] == "Damaged"
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 3

    untracked = await _create(client, auth_headers, title="No count", price=500, quantity=None)
    refused = await client.post(
        f"{_BASE}/adjustments",
        headers=auth_headers,
        json={"product_id": untracked["id"], "quantity": -1, "reason": "Lost"},
    )
    assert refused.status_code == 422
    assert "no stock count" in refused.json()["error"]["message"]


async def test_excel_import_saves_valid_rows_and_rejects_invalid_ones(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    kept = await _create(
        client, auth_headers, title="Named lamp", price=1000, quantity=10, cost_price="5.00"
    )
    other = await _create(
        client, auth_headers, title="Other lamp", price=1000, quantity=3, cost_price="2.00"
    )
    good = _sheet(
        (*PURCHASE_COLUMNS, "product_name"),
        [
            _cells(
                (*PURCHASE_COLUMNS, "product_name"),
                supplier_name="Karim Traders",
                invoice_no="INV-9",
                purchased_on="2026-11-01",
                product_id=kept["id"],
                quantity=4,
                unit_cost=7,
                product_name="This name must be ignored",
            )
        ],
    )
    preview = await _preview(client, auth_headers, "purchases", "purchases.xlsx", good)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["duplicate"] is False
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 0
    assert body["rows"][0]["valid"] is True
    purchases = await client.get(f"{_BASE}/purchases", headers=auth_headers)
    assert purchases.json()["total"] == 0

    saved = await _confirm(client, auth_headers, "purchases", "purchases.xlsx", good)
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] == 1
    assert saved.json()["skipped"] == 0
    received = await _stock(client, auth_headers, kept["id"])
    assert received["quantity"] == 14
    assert received["cost_price"] == 5.57
    assert (await _stock(client, auth_headers, other["id"]))["quantity"] == 3

    again = await _confirm(client, auth_headers, "purchases", "purchases.xlsx", good)
    assert again.status_code == 409
    assert "already imported" in again.json()["error"]["message"]
    assert (await _stock(client, auth_headers, kept["id"]))["quantity"] == 14

    forced = await _confirm(
        client, auth_headers, "purchases", "purchases.xlsx", good, duplicate=True
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["saved"] == 1
    assert (await _stock(client, auth_headers, kept["id"]))["quantity"] == 18

    bad = _sheet(
        (*PURCHASE_COLUMNS, "title"),
        [
            _cells(
                (*PURCHASE_COLUMNS, "title"),
                supplier_name="Karim Traders",
                purchased_on="2026-11-02",
                quantity=1,
                unit_cost=1,
                title="Named lamp",
            )
        ],
    )
    shown = await _preview(client, auth_headers, "purchases", "bad.xlsx", bad)
    assert shown.status_code == 200, shown.text
    assert shown.json()["valid_count"] == 0
    assert shown.json()["rows"][0]["valid"] is False
    assert any("never matched by name" in message for message in shown.json()["rows"][0]["errors"])
    rejected = await _confirm(client, auth_headers, "purchases", "bad.xlsx", bad)
    assert rejected.status_code == 422
    assert (await _stock(client, auth_headers, kept["id"]))["quantity"] == 18
    assert (await _stock(client, auth_headers, other["id"]))["quantity"] == 3

    mixed = _sheet(
        PURCHASE_COLUMNS,
        [
            _cells(
                PURCHASE_COLUMNS,
                supplier_name="Karim Traders",
                purchased_on="2026-11-03",
                product_id=other["id"],
                quantity=2,
                unit_cost=4,
            ),
            _cells(
                PURCHASE_COLUMNS,
                supplier_name="Karim Traders",
                purchased_on="2026-11-03",
                quantity=2,
                unit_cost=4,
            ),
        ],
    )
    mixed_preview = await _preview(client, auth_headers, "purchases", "mixed.xlsx", mixed)
    assert mixed_preview.status_code == 200, mixed_preview.text
    assert mixed_preview.json()["valid_count"] == 1
    assert mixed_preview.json()["invalid_count"] == 1
    mixed_saved = await _confirm(client, auth_headers, "purchases", "mixed.xlsx", mixed)
    assert mixed_saved.status_code == 200, mixed_saved.text
    assert mixed_saved.json()["saved"] == 1
    assert mixed_saved.json()["skipped"] == 1
    assert (await _stock(client, auth_headers, other["id"]))["quantity"] == 5
    assert (await _stock(client, auth_headers, kept["id"]))["quantity"] == 18

    text_file = await _preview(client, auth_headers, "purchases", "notes.txt", b"hello")
    assert text_file.status_code == 422
    fake = await _preview(client, auth_headers, "purchases", "purchases.xlsx", b"not a workbook")
    assert fake.status_code == 422
    assert (await _stock(client, auth_headers, kept["id"]))["quantity"] == 18


async def test_stock_count_opening_and_cost_imports(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(
        client, auth_headers, title="Counted import", price=500, quantity=10, cost_price="6.00"
    )
    counted = _sheet(
        STOCK_COUNT_COLUMNS,
        [_cells(STOCK_COUNT_COLUMNS, product_id=product["id"], counted_qty=8, reason="Damaged")],
    )
    preview = await _preview(client, auth_headers, "stock_count", "count.xlsx", counted)
    assert preview.status_code == 200, preview.text
    assert "10 → 8" in preview.json()["rows"][0]["summary"]
    saved = await _confirm(client, auth_headers, "stock_count", "count.xlsx", counted)
    assert saved.status_code == 200, saved.text
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 8
    assert (await _stock(client, auth_headers, product["id"]))["cost_price"] == 6
    adjustments = await _movements(client, auth_headers, product["id"], "adjustment")
    assert len(adjustments) == 1
    assert adjustments[0]["quantity"] == -2
    assert adjustments[0]["note"] == "Damaged"

    mismatch = _sheet(
        OPENING_COLUMNS,
        [_cells(OPENING_COLUMNS, product_id=product["id"], quantity=9)],
    )
    opening_preview = await _preview(client, auth_headers, "opening", "opening.xlsx", mismatch)
    assert opening_preview.status_code == 200, opening_preview.text
    assert any(
        "must equal the current stock" in message
        for message in opening_preview.json()["rows"][0]["errors"]
    )
    refused = await _confirm(client, auth_headers, "opening", "opening.xlsx", mismatch)
    assert refused.status_code == 422
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 8

    matched = _sheet(OPENING_COLUMNS, [_cells(OPENING_COLUMNS, product_id=product["id"])])
    opened = await _confirm(client, auth_headers, "opening", "opening-ok.xlsx", matched)
    assert opened.status_code == 200, opened.text
    assert opened.json()["saved"] == 1
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 8
    openings = await _movements(client, auth_headers, product["id"], "opening")
    assert len(openings) == 1
    assert openings[0]["quantity"] == 8

    costs = _sheet(
        COST_COLUMNS,
        [_cells(COST_COLUMNS, product_id=product["id"], unit_cost="12.50")],
    )
    priced = await _confirm(client, auth_headers, "cost_price", "costs.xlsx", costs)
    assert priced.status_code == 200, priced.text
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 8
    assert (await _stock(client, auth_headers, product["id"]))["cost_price"] == 12.5
    cost_rows = await _movements(client, auth_headers, product["id"], "adjustment")
    assert any(row["quantity"] == 0 and row["unit_cost"] == 12.5 for row in cost_rows)


async def test_sku_matches_and_a_product_name_does_not(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _make(client, auth_headers, title="Sku tee", cost_price="5.00")
    target = _variant(product, "red", "m")
    by_sku = _sheet(
        PURCHASE_COLUMNS,
        [
            _cells(
                PURCHASE_COLUMNS,
                supplier_name="SKU Traders",
                purchased_on="2026-11-04",
                sku="sku-red-m",
                quantity=1,
                unit_cost=11,
            )
        ],
    )
    saved = await _confirm(client, auth_headers, "purchases", "sku.xlsx", by_sku)
    assert saved.status_code == 200, saved.text
    fresh = await _stock(client, auth_headers, product["id"])
    assert _variant(fresh, "red", "m")["quantity"] == 4
    assert fresh["cost_price"] == 6.5
    rows = await _movements(client, auth_headers, product["id"], "purchase")
    assert rows[0]["variant_id"] == target["id"]


async def test_templates_and_exports_are_workbooks(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Exported lamp", price=500, quantity=2)
    template = await client.get(f"{_BASE}/imports/templates/purchases", headers=auth_headers)
    assert template.status_code == 200, template.text
    assert template.content.startswith(b"PK")
    book = load_workbook(BytesIO(template.content), read_only=True)
    headers = [cell.value for cell in next(book.worksheets[0].iter_rows(max_row=1))]
    book.close()
    assert tuple(headers) == PURCHASE_COLUMNS

    exported = await client.get(f"{_BASE}/exports/products", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    products = load_workbook(BytesIO(exported.content), read_only=True)
    values = list(products.worksheets[0].iter_rows(values_only=True))
    products.close()
    assert values[0][0] == "product_id"
    assert any(str(row[0]) == product["id"] for row in values[1:])

    future = date.today() + timedelta(days=2)
    empty = await client.get(
        f"{_BASE}/exports/movements",
        headers=auth_headers,
        params={"date_from": future.isoformat(), "date_to": future.isoformat()},
    )
    assert empty.status_code == 200, empty.text
    movements = load_workbook(BytesIO(empty.content), read_only=True)
    movement_rows = list(movements.worksheets[0].iter_rows(values_only=True))
    movements.close()
    assert len(movement_rows) == 1


async def test_roles_viewer_reads_and_editor_writes(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Guarded stock", price=500, quantity=4)
    viewer = await _staff(client, auth_headers, "ledger-viewer@implesia.com", "viewer")
    editor = await _staff(client, auth_headers, "ledger-editor@implesia.com", "editor")

    assert (await client.get(f"{_BASE}/movements", headers=viewer)).status_code == 200
    assert (await client.get(f"{_BASE}/exports/products", headers=viewer)).status_code == 200
    assert (
        await client.get(f"{_BASE}/imports/templates/opening", headers=viewer)
    ).status_code == 200
    blank = _sheet(OPENING_COLUMNS, [_cells(OPENING_COLUMNS, product_id=product["id"])])
    preview = await _preview(client, viewer, "opening", "opening.xlsx", blank)
    assert preview.status_code == 200, preview.text

    for path, body in (
        (f"{_BASE}/suppliers", {"name": "Blocked"}),
        (
            f"{_BASE}/purchases",
            {
                "supplier_id": str(uuid.uuid4()),
                "purchased_on": "2026-11-01",
                "items": [{"product_id": product["id"], "quantity": 1, "unit_cost": 1}],
            },
        ),
        (
            f"{_BASE}/adjustments",
            {"product_id": product["id"], "quantity": -1, "reason": "Lost"},
        ),
    ):
        denied = await client.post(path, headers=viewer, json=body)
        assert denied.status_code == 403, path
    assert (
        await client.post(f"{_BASE}/opening-stock", headers=viewer)
    ).status_code == 403
    confirm = await _confirm(client, viewer, "opening", "opening.xlsx", blank)
    assert confirm.status_code == 403
    assert (await client.get(f"{_BASE}/movements")).status_code == 401
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 4

    adjusted = await client.post(
        f"{_BASE}/adjustments",
        headers=editor,
        json={"product_id": product["id"], "quantity": -1, "reason": "Lost"},
    )
    assert adjusted.status_code == 201, adjusted.text
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 3


async def test_movement_update_and_delete_are_rejected(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    product = await _create(client, auth_headers, title="Frozen ledger", price=500, quantity=2)
    opened = await client.post(f"{_BASE}/opening-stock", headers=auth_headers)
    assert opened.status_code == 200, opened.text
    movement = (
        await db_session.scalars(
            select(StockMovement).where(StockMovement.product_id == uuid.UUID(product["id"]))
        )
    ).one()
    movement.note = "changed"
    with pytest.raises(RuntimeError, match="cannot be updated or deleted"):
        await db_session.flush()
    await db_session.rollback()
    again = (
        await db_session.scalars(
            select(StockMovement).where(StockMovement.product_id == uuid.UUID(product["id"]))
        )
    ).one()
    await db_session.delete(again)
    with pytest.raises(RuntimeError, match="cannot be updated or deleted"):
        await db_session.flush()
    await db_session.rollback()
    kept = await _movements(client, auth_headers, product["id"], "opening")
    assert len(kept) == 1
    assert kept[0]["note"] == "Opening stock from the current count"
