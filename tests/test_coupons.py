"""Coupon quote, checkout, admin, reports, and the Bangla error codes."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.audit_event import AuditEvent
from app.models.coupon import Coupon
from app.models.order import Order
from app.services import meta_capi
from app.services.coupon_service import discount_amount
from tests.test_catalog_categories import _cat
from tests.test_orders import SHIPPING, _key, _move
from tests.test_products import _create
from tests.test_site_footer import JPEG

ADMIN = "/api/v1/admin/coupons"
DHAKA = ZoneInfo("Asia/Dhaka")
INSIDE = {**SHIPPING, "district": "ঢাকা", "area": "গুলশান"}


def _coupon_body(**overrides: object) -> dict:
    body: dict = {
        "code": "SAVE10",
        "discount_type": "percent",
        "value": 10,
    }
    body.update(overrides)
    return body


async def _coupon(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> dict:
    response = await client.post(ADMIN, headers=headers, json=_coupon_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _items(product_id: str, quantity: int = 1) -> list[dict]:
    return [{"product_id": product_id, "quantity": quantity}]


def _direct(product_id: str, **extra: object) -> dict:
    quantity = int(extra.pop("quantity", 1))  # type: ignore[arg-type]
    body: dict = {
        "source": "direct",
        "items": _items(product_id, quantity),
        **INSIDE,
    }
    body.update(extra)
    return body


async def _quote(client: AsyncClient, product_id: str, **extra: object) -> dict:
    quantity = int(extra.pop("quantity", 1))  # type: ignore[arg-type]
    body: dict = {
        "source": "direct",
        "district": "ঢাকা",
        "area": "গুলশান",
        "items": _items(product_id, quantity),
    }
    body.update(extra)
    response = await client.post("/api/v1/orders/quote", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def _place(client: AsyncClient, product_id: str, **extra: object):
    return await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_direct(product_id, **extra),
    )


def _error(response) -> tuple[str, str]:
    body = response.json()["error"]
    return body["code"], body["message"]


def test_discount_math_caps_percent_and_fixed() -> None:
    percent = Coupon(code="P", discount_type="percent", value=Decimal("10.5"))
    assert discount_amount(percent, 1000) == 105
    capped = Coupon(
        code="C", discount_type="percent", value=Decimal("50"), max_discount=120
    )
    assert discount_amount(capped, 1000) == 120
    fixed = Coupon(code="F", discount_type="fixed", value=Decimal("5000"))
    assert discount_amount(fixed, 1000) == 1000
    assert discount_amount(fixed, 0) == 0


async def test_percent_coupon_applies_after_quantity_discount(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=5, title="Sari")
    await _coupon(client, auth_headers)
    quoted = await _quote(client, product["id"], coupon_code="save10")
    assert quoted["subtotal"] == 1000
    assert quoted["shipping"] == 70
    assert quoted["total"] == 970
    assert quoted["coupon"] == {
        "code": "SAVE10",
        "valid": True,
        "discount": 100,
        "free_delivery": False,
        "error_code": None,
        "message": None,
    }

    two = await _quote(client, product["id"], quantity=2, coupon_code="SAVE10")
    # 2 × 1000 at 0.25% is 1995, then 10% off that payable is 199.
    assert two["subtotal"] == 1995
    assert two["coupon"]["discount"] == 199
    assert two["total"] == 1866

    placed = await _place(client, product["id"], coupon_code="SAVE10")
    assert placed.status_code == 201, placed.text
    body = placed.json()
    assert body["coupon_code"] == "SAVE10"
    assert body["coupon_discount"] == 100
    assert body["subtotal"] == 1000
    assert body["total"] == 970

    looked = await client.post(
        "/api/v1/orders/lookup",
        json={"number": body["number"], "phone": INSIDE["phone"]},
    )
    assert looked.status_code == 200, looked.text
    assert looked.json()["coupon_code"] == "SAVE10"
    assert looked.json()["coupon_discount"] == 100
    admin = await client.get(f"/api/v1/admin/orders/{body['id']}", headers=auth_headers)
    assert admin.status_code == 200, admin.text
    assert admin.json()["coupon_discount"] == 100


async def test_fixed_cap_free_delivery_and_no_coupon(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=4, title="Lamp")
    await _coupon(
        client,
        auth_headers,
        code="TAKE150",
        discount_type="fixed",
        value=150,
    )
    fixed = await _quote(client, product["id"], coupon_code="take150")
    assert fixed["coupon"]["discount"] == 150
    assert fixed["total"] == 920

    await _coupon(
        client,
        auth_headers,
        code="HUGE",
        discount_type="fixed",
        value=5000,
    )
    huge = await _place(client, product["id"], coupon_code="HUGE", phone="01711111111")
    assert huge.status_code == 201, huge.text
    assert huge.json()["coupon_discount"] == 1000
    assert huge.json()["subtotal"] == 1000
    assert huge.json()["total"] == 70

    await _coupon(
        client,
        auth_headers,
        code="FREESHIP",
        discount_type="fixed",
        value=100,
        free_delivery=True,
    )
    free = await _place(client, product["id"], coupon_code="FREESHIP", phone="01722222222")
    assert free.status_code == 201, free.text
    assert free.json()["shipping"] == 0
    assert free.json()["coupon_discount"] == 100
    assert free.json()["total"] == 900

    plain = await _place(client, product["id"], phone="01733333333")
    assert plain.status_code == 201, plain.text
    assert plain.json()["coupon_code"] is None
    assert plain.json()["coupon_discount"] is None
    assert plain.json()["total"] == plain.json()["subtotal"] + plain.json()["shipping"]

    blank = await _quote(client, product["id"], coupon_code="  ")
    assert blank["coupon"] is None
    assert blank["total"] == blank["subtotal"] + blank["shipping"]


async def test_max_cap_and_client_money_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=3, title="Cap")
    await _coupon(
        client,
        auth_headers,
        code="HALF",
        discount_type="percent",
        value=50,
        max_discount=120,
    )
    quoted = await _quote(client, product["id"], coupon_code="HALF")
    assert quoted["coupon"]["discount"] == 120
    assert quoted["total"] == 950

    rejected = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            **_direct(product["id"], coupon_code="HALF"),
            "coupon_discount": 99999,
            "total": 1,
        },
    )
    assert rejected.status_code == 422
    placed = await _place(client, product["id"], coupon_code="HALF")
    assert placed.status_code == 201, placed.text
    assert placed.json()["coupon_discount"] == 120
    assert placed.json()["total"] == 950


async def test_invalid_coupon_keeps_the_quote_and_rejects_the_order(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=2, title="Missing")
    bare = await _quote(client, product["id"])
    bad = await _quote(client, product["id"], coupon_code="NOPE")
    assert bad["total"] == bare["total"]
    assert bad["coupon"]["valid"] is False
    assert bad["coupon"]["error_code"] == "coupon_not_found"
    assert "পাওয়া যায়নি" in bad["coupon"]["message"]

    refused = await _place(client, product["id"], coupon_code="NOPE")
    assert refused.status_code == 422
    code, message = _error(refused)
    assert code == "coupon_not_found"
    assert "পাওয়া যায়নি" in message
    stock = await client.get(f"/api/v1/admin/products/{product['id']}", headers=auth_headers)
    assert stock.json()["quantity"] == 2


async def test_min_amount_window_and_inactive_messages(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=3, title="Window")
    now = datetime.now(DHAKA)
    await _coupon(client, auth_headers, code="MIN1500", min_order_amount=1500)
    low = await _quote(client, product["id"], coupon_code="MIN1500")
    assert low["coupon"]["valid"] is False
    assert low["coupon"]["error_code"] == "coupon_min_amount"
    assert "৳১,৫০০" in low["coupon"]["message"]
    assert low["total"] == 1070

    await _coupon(
        client,
        auth_headers,
        code="LATER",
        starts_at=(now + timedelta(days=2)).isoformat(),
        ends_at=(now + timedelta(days=9)).isoformat(),
    )
    later = await _quote(client, product["id"], coupon_code="LATER")
    assert later["coupon"]["error_code"] == "coupon_not_started"
    assert "এখনো চালু হয়নি" in later["coupon"]["message"]

    await _coupon(
        client,
        auth_headers,
        code="OLD",
        starts_at=(now - timedelta(days=3)).isoformat(),
        ends_at=(now - timedelta(hours=1)).isoformat(),
    )
    old = await _quote(client, product["id"], coupon_code="OLD")
    assert old["coupon"]["error_code"] == "coupon_expired"
    assert "মেয়াদ শেষ" in old["coupon"]["message"]

    closed = await _coupon(client, auth_headers, code="OFF", is_active=False)
    assert closed["status"] == "inactive"
    off = await _quote(client, product["id"], coupon_code="OFF")
    assert off["coupon"]["error_code"] == "coupon_inactive"

    naive = await _coupon(client, auth_headers, code="NAIVE", starts_at="2099-06-01T00:00:00")
    assert datetime.fromisoformat(naive["starts_at"]) == datetime(2099, 6, 1, tzinfo=DHAKA)
    assert naive["status"] == "scheduled"
    create_later = await _place(client, product["id"], coupon_code="LATER")
    assert _error(create_later)[0] == "coupon_not_started"


async def test_limits_first_order_and_cancel_restores_the_use(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=8, title="Limit")
    limited = await _coupon(client, auth_headers, code="ONCE", usage_limit_total=1)
    first = await _place(client, product["id"], coupon_code="ONCE", phone="01710000001")
    assert first.status_code == 201, first.text
    second = await _place(client, product["id"], coupon_code="ONCE", phone="01710000002")
    assert _error(second) == (
        "coupon_usage_limit",
        "এই কুপনটি ব্যবহারের সর্বোচ্চ সীমায় পৌঁছে গেছে।",
    )
    quoted = await _quote(client, product["id"], coupon_code="ONCE")
    assert quoted["coupon"]["error_code"] == "coupon_usage_limit"
    assert quoted["total"] == 1070

    cancelled = await _move(client, auth_headers, first.json()["id"], "cancelled")
    assert cancelled.status_code == 200, cancelled.text
    again = await _place(client, product["id"], coupon_code="ONCE", phone="01710000003")
    assert again.status_code == 201, again.text
    listed = await client.get(f"{ADMIN}/{limited['id']}", headers=auth_headers)
    assert listed.json()["used_count"] == 1

    await _coupon(
        client,
        auth_headers,
        code="PHONE1",
        usage_limit_per_phone=1,
        discount_type="fixed",
        value=50,
    )
    same = await _place(client, product["id"], coupon_code="PHONE1", phone="+8801710000004")
    assert same.status_code == 201, same.text
    repeat = await _place(client, product["id"], coupon_code="PHONE1", phone="01710000004")
    assert _error(repeat)[0] == "coupon_phone_limit"
    other = await _place(client, product["id"], coupon_code="PHONE1", phone="01710000005")
    assert other.status_code == 201, other.text
    preview = await _quote(
        client, product["id"], coupon_code="PHONE1", phone="01710000004"
    )
    assert preview["coupon"]["error_code"] == "coupon_phone_limit"
    assert preview["coupon"]["valid"] is False

    await _coupon(client, auth_headers, code="FIRST", first_order_only=True, value=5)
    prior = await _place(client, product["id"], phone="01710000006")
    assert prior.status_code == 201, prior.text
    blocked = await _place(client, product["id"], coupon_code="FIRST", phone="01710000006")
    assert _error(blocked)[0] == "coupon_first_order_only"
    assert "প্রথম অর্ডারে" in _error(blocked)[1]
    fresh = await _place(client, product["id"], coupon_code="FIRST", phone="01710000007")
    assert fresh.status_code == 201, fresh.text
    quiet = await _quote(client, product["id"], coupon_code="FIRST")
    assert quiet["coupon"]["valid"] is True
    known = await _quote(
        client, product["id"], coupon_code="FIRST", phone="01710000006"
    )
    assert known["coupon"]["error_code"] == "coupon_first_order_only"

    dropped = await _place(client, product["id"], phone="01710000008")
    await _move(client, auth_headers, dropped.json()["id"], "cancelled")
    after_cancel = await _place(
        client, product["id"], coupon_code="FIRST", phone="01710000008"
    )
    assert after_cancel.status_code == 201, after_cancel.text


async def test_a_return_keeps_the_redemption(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=3, title="Return")
    coupon = await _coupon(client, auth_headers, code="KEEP", usage_limit_total=1)
    placed = await _place(client, product["id"], coupon_code="KEEP", phone="01710000009")
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]
    for status in ("confirmed", "shipped", "delivered", "returned"):
        moved = await _move(client, auth_headers, order_id, status)
        assert moved.status_code == 200, moved.text
    detail = await client.get(f"{ADMIN}/{coupon['id']}", headers=auth_headers)
    assert detail.json()["used_count"] == 1
    history = await client.get(f"{ADMIN}/{coupon['id']}/redemptions", headers=auth_headers)
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["status"] == "active"
    assert history.json()["items"][0]["cancelled_at"] is None
    blocked = await _place(client, product["id"], coupon_code="KEEP", phone="01710000010")
    assert _error(blocked)[0] == "coupon_usage_limit"


async def test_product_and_category_restrictions(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    parent = await _cat(client, auth_headers, "কাপড়")
    child = await _cat(client, auth_headers, "শাড়ি", parent["id"])
    other = await _cat(client, auth_headers, "জুতা")
    sharee = await _create(
        client,
        auth_headers,
        title="Sharee",
        price=1000,
        quantity=4,
        category_id=child["id"],
    )
    shoe = await _create(
        client,
        auth_headers,
        title="Shoe",
        price=1000,
        quantity=4,
        category_id=other["id"],
    )
    await _coupon(
        client,
        auth_headers,
        code="CLOTH",
        category_ids=[parent["id"]],
    )
    both = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "ঢাকা",
            "area": "গুলশান",
            "coupon_code": "CLOTH",
            "items": [
                {"product_id": sharee["id"], "quantity": 1},
                {"product_id": shoe["id"], "quantity": 1},
            ],
        },
    )
    assert both.status_code == 200, both.text
    mixed = both.json()
    assert mixed["subtotal"] == 2000
    assert mixed["coupon"]["discount"] == 100
    assert mixed["total"] == 1970

    none = await _quote(client, shoe["id"], coupon_code="CLOTH")
    assert none["coupon"]["error_code"] == "coupon_not_eligible"
    assert "কোনো পণ্য নেই" in none["coupon"]["message"]
    refused = await _place(client, shoe["id"], coupon_code="CLOTH")
    assert _error(refused)[0] == "coupon_not_eligible"

    await _coupon(client, auth_headers, code="ONLY", product_ids=[sharee["id"]])
    only = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "coupon_code": "ONLY",
            "items": [
                {"product_id": sharee["id"], "quantity": 1},
                {"product_id": shoe["id"], "quantity": 1},
            ],
            **INSIDE,
            "phone": "01710000011",
        },
    )
    assert only.status_code == 201, only.text
    assert only.json()["coupon_discount"] == 100
    assert only.json()["subtotal"] == 2000
    assert only.json()["total"] == 1970


async def test_admin_list_edit_roles_and_audit(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    created = await _coupon(client, auth_headers, code="eid_50", value=20)
    assert created["code"] == "EID_50"
    assert created["used_count"] == 0
    assert created["created_by"]
    duplicate = await client.post(ADMIN, headers=auth_headers, json=_coupon_body(code="eid-50"))
    # hyphen differs; the case-only duplicate is the conflict
    assert duplicate.status_code == 201, duplicate.text
    clash = await client.post(ADMIN, headers=auth_headers, json=_coupon_body(code="Eid_50"))
    assert clash.status_code == 409
    assert clash.json()["error"]["message"] == "এই কুপন কোডটি আগে থেকেই আছে।"
    short = await client.post(ADMIN, headers=auth_headers, json=_coupon_body(code="ab"))
    assert short.status_code == 422

    found = await client.get(
        ADMIN, headers=auth_headers, params={"q": "eid_50", "status": "active"}
    )
    assert found.status_code == 200, found.text
    assert found.json()["total"] == 1
    assert found.json()["items"][0]["code"] == "EID_50"

    page = await client.get(ADMIN, headers=auth_headers, params={"page_size": 1, "page": 1})
    assert page.json()["page_size"] == 1
    assert page.json()["pages"] >= 2

    renamed = await client.patch(
        f"{ADMIN}/{created['id']}",
        headers=auth_headers,
        json={"code": "EID20", "max_discount": 80},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["code"] == "EID20"
    assert renamed.json()["max_discount"] == 80

    off = await client.post(f"{ADMIN}/{created['id']}/deactivate", headers=auth_headers)
    assert off.json()["is_active"] is False
    assert off.json()["status"] == "inactive"
    inactive = await client.get(ADMIN, headers=auth_headers, params={"status": "inactive"})
    assert any(item["id"] == created["id"] for item in inactive.json()["items"])
    on = await client.post(f"{ADMIN}/{created['id']}/activate", headers=auth_headers)
    assert on.json()["status"] == "active"

    viewer = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "coupon-viewer@implesia.com",
            "full_name": "Coupon Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert viewer.status_code in (200, 201), viewer.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "coupon-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get(ADMIN, headers=headers)).status_code == 200
    denied = await client.post(ADMIN, headers=headers, json=_coupon_body(code="NOPE1"))
    assert denied.status_code == 403

    events = (
        await db_session.scalars(select(AuditEvent).where(AuditEvent.action == "ADMIN_WRITE"))
    ).all()
    paths = [event.event_metadata.get("path", "") for event in events]
    assert any(path.endswith("/api/v1/admin/coupons") for path in paths)
    assert any("/deactivate" in path for path in paths)


async def test_cancel_redemption_history_and_meta_coupon(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=2, title="Meta")
    coupon = await _coupon(client, auth_headers, code="META10")
    placed = await _place(client, product["id"], coupon_code="meta10", phone="01710000012")
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]
    history = await client.get(f"{ADMIN}/{coupon['id']}/redemptions", headers=auth_headers)
    assert history.json()["total"] == 1
    row = history.json()["items"][0]
    assert row["phone"] == "01710000012"
    assert row["discount_amount"] == 100
    assert row["status"] == "active"
    assert row["order_number"] == placed.json()["number"]

    await _move(client, auth_headers, order_id, "cancelled")
    after = await client.get(f"{ADMIN}/{coupon['id']}/redemptions", headers=auth_headers)
    assert after.json()["items"][0]["status"] == "cancelled"
    assert after.json()["items"][0]["cancelled_at"] is not None
    detail = await client.get(f"{ADMIN}/{coupon['id']}", headers=auth_headers)
    assert detail.json()["used_count"] == 0

    loaded = await db_session.scalar(
        select(Order).options(selectinload(Order.items)).where(Order.id == uuid.UUID(order_id))
    )
    assert loaded is not None
    purchase = meta_capi.build_purchase_body(loaded, None)
    assert purchase["data"][0]["custom_data"]["coupon"] == "META10"
    assert purchase["data"][0]["custom_data"]["value"] == loaded.total

    plain = await _place(client, product["id"], phone="01710000013")
    bare = await db_session.scalar(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == uuid.UUID(plain.json()["id"]))
    )
    assert bare is not None
    assert "coupon" not in meta_capi.build_purchase_body(bare, None)["data"][0]["custom_data"]


async def test_bangla_qr_uses_the_discounted_total(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    uploaded = await client.post(
        "/api/v1/admin/site/payment/qr",
        headers=auth_headers,
        files={"image": ("qr.jpg", JPEG, "image/jpeg")},
    )
    assert uploaded.status_code == 200, uploaded.text
    product = await _create(client, auth_headers, price=1000, quantity=2, title="QR")
    await _coupon(client, auth_headers, code="QR10")
    quoted = await _quote(client, product["id"], coupon_code="QR10")
    options = {option["percent"]: option for option in quoted["bangla_qr_options"]}
    assert options[25] == {"percent": 25, "advance": 243, "due": 727}
    assert options[100] == {"percent": 100, "advance": 970, "due": 0}

    placed = await _place(
        client,
        product["id"],
        coupon_code="QR10",
        payment_method="bangla_qr",
        advance_percent=25,
        payment_reference="TXN12345",
    )
    assert placed.status_code == 201, placed.text
    body = placed.json()
    assert body["total"] == 970
    assert body["advance_amount"] == 243
    assert body["due_amount"] == 727


async def test_reports_are_net_of_the_coupon_and_export(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    known = await _create(
        client, auth_headers, price=1000, quantity=4, title="Known lamp", cost_price="400.00"
    )
    plain = await _create(client, auth_headers, price=500, quantity=4, title="Plain")
    await _coupon(client, auth_headers, code="NET10")
    discounted = await _place(client, known["id"], coupon_code="NET10", phone="01710000014")
    untouched = await _place(client, plain["id"], phone="01710000015")
    assert discounted.status_code == 201, discounted.text
    assert untouched.status_code == 201, untouched.text
    for order_id in (discounted.json()["id"], untouched.json()["id"]):
        for status in ("confirmed", "shipped", "delivered"):
            moved = await _move(client, auth_headers, order_id, status)
            assert moved.status_code == 200, moved.text

    today = datetime.now(DHAKA).date().isoformat()
    params = {"from": today, "to": today}
    sales = await client.get("/api/v1/admin/reports/sales", headers=auth_headers, params=params)
    assert sales.status_code == 200, sales.text
    body = sales.json()
    assert body["gross_sales"] == 1500
    assert body["coupon_discount"] == 100
    assert body["discount"] == 100
    assert body["delivery_charge"] == 140
    assert body["net_sales"] == 1540

    profit = await client.get("/api/v1/admin/reports/profit", headers=auth_headers, params=params)
    earned = profit.json()
    assert earned["revenue"] == 900
    assert earned["cost"] == 400
    assert earned["profit"] == 500
    assert earned["unknown_cost_revenue"] == 500

    products = await client.get(
        "/api/v1/admin/reports/products", headers=auth_headers, params=params
    )
    rows = {row["title"]: row for row in products.json()["items"]}
    assert rows["Known lamp"]["revenue"] == 900
    assert rows["Plain"]["revenue"] == 500

    trend = await client.get("/api/v1/admin/reports/trend", headers=auth_headers, params=params)
    assert trend.json()["points"][-1]["net_sales"] == 1540

    coupons = await client.get(
        "/api/v1/admin/reports/coupons", headers=auth_headers, params=params
    )
    assert coupons.status_code == 200, coupons.text
    report = coupons.json()
    assert report["filters"]["channel_applies"] is False
    assert report["times_used"] == 1
    assert report["total_discount"] == 100
    assert report["total_sales"] == 970
    assert report["items"][0]["code"] == "NET10"

    exported = await client.get(
        "/api/v1/admin/reports/coupons/export", headers=auth_headers, params=params
    )
    assert exported.status_code == 200, exported.text
    book = load_workbook(BytesIO(exported.content), data_only=True)
    sheet = book.active
    assert sheet is not None
    grid = [tuple(row) for row in sheet.iter_rows(values_only=True)]
    flat = [cell for row in grid for cell in row]
    assert "NET10" in flat
    assert "Asia/Dhaka" in flat
    header_at = next(index for index, row in enumerate(grid) if row and row[0] == "Code")
    assert grid[header_at + 1][0] == "NET10"
    assert grid[header_at + 1][2] == 100
