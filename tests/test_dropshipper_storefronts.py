"""Phase 35 tests: Multi-tenant dropshipper storefronts, strict SEO/tracking & public checkout."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.services import meta_capi, order_service
from tests.conftest import TEST_PASSWORD


async def _create_approved_dropshipper(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    phone: str = "01733000001",
    email: str = "store1@example.com",
    shop_name: str = "Nova Fashion BD",
) -> tuple[dict[str, str], str]:
    reg = await client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Store Owner",
            "phone": phone,
            "email": email,
            "password": TEST_PASSWORD,
        },
    )
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    apply_res = await client.post(
        "/api/v1/dropshipper/apply",
        headers=headers,
        json={
            "shop_name": shop_name,
            "shop_phone": phone,
            "shop_address": "Banani, Dhaka",
            "payout_method": "bkash",
            "payout_account_number": phone,
            "payout_account_name": "Store Owner",
        },
    )
    assert apply_res.status_code == 201, apply_res.text
    profile_id = apply_res.json()["id"]
    appr = await client.post(
        f"/api/v1/admin/dropshipping/partners/{profile_id}/approve",
        headers=auth_headers,
    )
    assert appr.status_code == 200, appr.text
    return headers, profile_id


async def _create_dropship_product(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    title: str = "Slim Fit Shirt",
    cost_price: int = 350,
    dropship_price: int = 550,
    retail_price: int = 950,
    min_sell_price: int = 600,
    max_sell_price: int = 1500,
    quantity: int = 30,
) -> dict[str, Any]:
    cat = await client.post(
        "/api/v1/admin/categories",
        headers=auth_headers,
        data={"payload": json.dumps({"name": f"Apparel-{uuid.uuid4().hex[:6]}"})},
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
                    "subtitle": "Export quality",
                    "category_id": cat_id,
                    "price": retail_price,
                    "cost_price": cost_price,
                    "quantity": quantity,
                    "weight_grams": 350,
                    "image_src": "/media/products/shirt.jpg",
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
    return dict(prod.json())


def test_migration_0119_is_single_head_chained_to_0118() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0119"]
    rev = script.get_revision("0119")
    assert rev is not None
    assert rev.down_revision == "0118"


async def test_store_xss_tracking_regex_reserved_slug_and_secret_masking(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    ds_headers, _pid = await _create_approved_dropshipper(
        client, auth_headers, phone="01733000011", email="xss@example.com"
    )

    # Auto-provision on first GET
    me_store = await client.get("/api/v1/dropshipper/store", headers=ds_headers)
    assert me_store.status_code == 200, me_store.text
    store = me_store.json()
    assert store["template_id"] == "modern_tech"
    assert store["is_published"] is False
    assert store["has_meta_capi_token"] is False
    assert "meta_capi_token" not in store

    # Reserved slug rejected
    bad_slug = await client.patch(
        "/api/v1/dropshipper/store",
        headers=ds_headers,
        json={"slug": "admin"},
    )
    assert bad_slug.status_code == 422

    # Invalid hex color rejected
    bad_hex = await client.patch(
        "/api/v1/dropshipper/store",
        headers=ds_headers,
        json={"theme_config": {"primary_color": "red;background:url(x)"}},
    )
    assert bad_hex.status_code == 422

    # XSS / invalid tracking IDs strictly rejected
    for bad_payload in (
        {"meta_pixel_id": "<script>alert(1)</script>"},
        {"gtm_id": "GTM-bad<script>"},
        {"ga4_measurement_id": "UA-12345"},
        {"tiktok_pixel_id": "invalid space!"},
        {"google_site_verification": "<meta name=x>"},
    ):
        res = await client.patch(
            "/api/v1/dropshipper/store/seo-tracking",
            headers=ds_headers,
            json=bad_payload,
        )
        assert res.status_code == 422, f"Expected 422 for {bad_payload}, got {res.status_code}"

    # Valid tracking IDs + secret CAPI token succeed, and token is masked
    ok_seo = await client.patch(
        "/api/v1/dropshipper/store/seo-tracking",
        headers=ds_headers,
        json={
            "seo_title": "Nova Fashion BD — Official Store",
            "seo_description": "Best apparel in Bangladesh.",
            "meta_pixel_id": "123456789012345",
            "meta_capi_token": "EAAGm0PX4ZCpsSUPERSECRETTOKEN12345",
            "gtm_id": "GTM-ABCD123",
            "ga4_measurement_id": "G-XYZ987654",
            "tiktok_pixel_id": "C9ABCD1234EFGH",
            "google_site_verification": "abc123XYZ_verification-token",
        },
    )
    assert ok_seo.status_code == 200, ok_seo.text
    seo_data = ok_seo.json()
    assert seo_data["has_meta_capi_token"] is True
    assert "meta_capi_token" not in seo_data
    assert "SUPERSECRETTOKEN" not in ok_seo.text

    # Publish store with custom slug & template
    pub = await client.patch(
        "/api/v1/dropshipper/store",
        headers=ds_headers,
        json={
            "slug": "nova-fashion-bd",
            "is_published": True,
            "template_id": "minimal_boutique",
        },
    )
    assert pub.status_code == 200, pub.text

    # Public endpoint returns store with tracking IDs, NEVER leaks meta_capi_token
    public_res = await client.get("/api/v1/public/stores/nova-fashion-bd")
    assert public_res.status_code == 200, public_res.text
    pub_json = public_res.json()
    assert pub_json["slug"] == "nova-fashion-bd"
    assert pub_json["template_id"] == "minimal_boutique"
    assert pub_json["meta_pixel_id"] == "123456789012345"
    assert pub_json["gtm_id"] == "GTM-ABCD123"
    assert "meta_capi_token" not in pub_json
    assert "has_meta_capi_token" not in pub_json
    assert "SUPERSECRETTOKEN" not in public_res.text


async def test_public_store_live_stock_auto_hide_and_direct_checkout(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ds_headers, profile_id = await _create_approved_dropshipper(
        client,
        auth_headers,
        phone="01733000022",
        email="checkout@example.com",
        shop_name="Apex Hub",
    )
    product = await _create_dropship_product(client, auth_headers)
    product_id = product["id"]
    product_slug = product["slug"]

    # Configure & publish store with Meta Pixel + CAPI token
    await client.get("/api/v1/dropshipper/store", headers=ds_headers)
    await client.patch(
        "/api/v1/dropshipper/store",
        headers=ds_headers,
        json={"slug": "apex-hub", "is_published": True, "template_id": "flash_deal"},
    )
    await client.patch(
        "/api/v1/dropshipper/store/seo-tracking",
        headers=ds_headers,
        json={
            "meta_pixel_id": "998877665544332",
            "meta_capi_token": "EAAG_DROPSHIP_SECRET_TOKEN",
        },
    )

    # Import below min_sell_price rejected
    bad_import = await client.post(
        "/api/v1/dropshipper/store/products",
        headers=ds_headers,
        json={"items": [{"product_id": product_id, "selling_price": 560}]},
    )
    assert bad_import.status_code == 422

    # Valid import succeeds
    imp = await client.post(
        "/api/v1/dropshipper/store/products",
        headers=ds_headers,
        json={
            "items": [
                {
                    "product_id": product_id,
                    "custom_title": "Apex Signature Shirt",
                    "selling_price": 1050,
                    "compare_at_price": 1350,
                    "is_featured": True,
                }
            ]
        },
    )
    assert imp.status_code == 201, imp.text
    assert imp.json()["total"] == 1
    assert imp.json()["items"][0]["estimated_profit"] == 500

    # Public products API NEVER leaks dropship_price, cost_price, or supplier_id
    pub_prods = await client.get("/api/v1/public/stores/apex-hub/products")
    assert pub_prods.status_code == 200, pub_prods.text
    p_item = pub_prods.json()["items"][0]
    assert p_item["title"] == "Apex Signature Shirt"
    assert p_item["selling_price"] == 1050
    assert p_item["stock_quantity"] == 30
    assert "dropship_price" not in p_item
    assert "cost_price" not in p_item
    assert "supplier_id" not in p_item

    # Single product detail works
    pub_detail = await client.get(f"/api/v1/public/stores/apex-hub/products/{product_slug}")
    assert pub_detail.status_code == 200

    # Public quote works
    q_res = await client.post(
        "/api/v1/public/stores/apex-hub/orders/quote",
        json={
            "items": [{"product_id": product_id, "quantity": 2}],
            "district": "Dhaka",
            "area": "Uttara",
        },
    )
    assert q_res.status_code == 200, q_res.text
    assert q_res.json()["subtotal"] == 2100

    # Capture custom Meta CAPI call on direct storefront checkout
    capi_calls: list[dict[str, Any]] = []

    async def _fake_send_custom(
        order_number: str,
        body: dict[str, Any],
        *,
        pixel_id: str,
        access_token: str,
    ) -> None:
        capi_calls.append(
            {
                "order_number": order_number,
                "pixel_id": pixel_id,
                "access_token": access_token,
                "event_id": body["data"][0]["event_id"],
            }
        )

    monkeypatch.setattr(meta_capi, "send_custom_purchase", _fake_send_custom)

    # End customer places COD order directly on /s/apex-hub!
    order_res = await client.post(
        "/api/v1/public/stores/apex-hub/orders",
        headers={"Idempotency-Key": f"pub-store-{uuid.uuid4().hex}"},
        json={
            "items": [{"product_id": product_id, "quantity": 2}],
            "customer_name": "Storefront Buyer",
            "phone": "01855667788",
            "district": "Dhaka",
            "area": "Uttara",
            "address": "Sector 7, Uttara, Dhaka",
            "note": "Deliver in evening",
        },
    )
    assert order_res.status_code == 201, order_res.text
    o_data = order_res.json()
    assert o_data["subtotal"] == 2100
    assert o_data["analytics_event_id"] == f"purchase_{o_data['order_number']}"

    # Verify custom Meta CAPI fired with dropshipper's own Pixel + matching event_id!
    assert len(capi_calls) == 1
    assert capi_calls[0]["pixel_id"] == "998877665544332"
    assert capi_calls[0]["event_id"] == o_data["analytics_event_id"]

    # Verify order routed into dropship engine & delivering credits dropshipper's wallet!
    order_row = await db_session.scalar(
        select(Order).where(Order.number == o_data["order_number"])
    )
    assert order_row is not None
    assert order_row.channel == "dropship"
    assert order_row.white_label_shop_name == "Apex Hub"
    assert order_row.dropship_profit_amount == 1000  # (1050 - 550) * 2

    for step in (
        OrderStatus.CONFIRMED.value,
        OrderStatus.PACKED.value,
        OrderStatus.SHIPPED.value,
        OrderStatus.DELIVERED.value,
    ):
        await order_service.change_status(db_session, order_row, step, actor_id=None)
        await db_session.refresh(order_row)
    await db_session.commit()

    wallet = (await client.get("/api/v1/dropshipper/wallet", headers=ds_headers)).json()
    assert wallet["pending_balance"] == 1000

    # Auto-hide when admin disables allow_dropshipping=False on upstream product
    disable_res = await client.patch(
        f"/api/v1/admin/products/{product_id}",
        headers=auth_headers,
        data={"payload": json.dumps({"allow_dropshipping": False})},
    )
    assert disable_res.status_code == 200, disable_res.text

    pub_after_hide = await client.get("/api/v1/public/stores/apex-hub/products")
    assert pub_after_hide.status_code == 200
    assert pub_after_hide.json()["total"] == 0

    # Suspending dropshipper returns 404 on public storefront
    susp = await client.post(
        f"/api/v1/admin/dropshipping/partners/{profile_id}/suspend",
        headers=auth_headers,
        json={"reason": "Policy review"},
    )
    assert susp.status_code == 200
    pub_suspended = await client.get("/api/v1/public/stores/apex-hub")
    assert pub_suspended.status_code == 404
