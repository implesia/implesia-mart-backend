"""Phase 31 tests: Dropshipping schema, RBAC isolation, KYC onboarding, catalog & settings."""

import io
import json
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditAction, AuditEvent
from app.models.notification import CustomerNotification
from app.models.role import Role
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services import user_service
from tests.conftest import TEST_PASSWORD

_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _register_customer(
    client: AsyncClient,
    *,
    phone: str = "01711223344",
    email: str = "partner1@example.com",
    full_name: str = "Rafiqul Islam",
) -> tuple[dict[str, str], str]:
    res = await client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": full_name,
            "phone": phone,
            "email": email,
            "password": TEST_PASSWORD,
        },
    )
    assert res.status_code == 201, res.text
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    prof = await client.get("/api/v1/customer/profile", headers=headers)
    assert prof.status_code == 200, prof.text
    return headers, prof.json()["id"]


def test_migration_0118_is_single_head_chained_to_0117() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads == ["0118"]
    rev = script.get_revision("0118")
    assert rev is not None
    assert rev.down_revision == "0117"


async def test_dropshipper_role_blocked_from_admin_login_and_admin_apis(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    role = await db_session.scalar(select(Role).where(Role.slug == UserRole.DROPSHIPPER.value))
    assert role is not None
    assert role.admin_access is False
    assert role.is_system is True
    assert role.category == "storefront"

    user = await user_service.create_user(
        db_session,
        UserCreate(
            email="drop.only@example.com",
            full_name="Drop Partner",
            password=TEST_PASSWORD,
            role=UserRole.DROPSHIPPER.value,
        ),
    )
    assert user.role == UserRole.DROPSHIPPER.value

    # Strictly blocked from staff /api/v1/auth/login
    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "drop.only@example.com", "password": TEST_PASSWORD},
    )
    assert admin_login.status_code == 403, admin_login.text

    # Can sign in via customer login, but still strictly blocked from /api/v1/admin/*
    cust_login = await client.post(
        "/api/v1/customer/auth/login",
        json={"identifier": "drop.only@example.com", "password": TEST_PASSWORD},
    )
    assert cust_login.status_code == 200, cust_login.text
    drop_headers = {"Authorization": f"Bearer {cust_login.json()['access_token']}"}

    blocked = await client.get("/api/v1/admin/dropshipping/overview", headers=drop_headers)
    assert blocked.status_code == 403


async def test_kyc_apply_reject_reapply_approve_suspend_reactivate_and_staff_safety(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    cust_headers, user_id = await _register_customer(client)

    # Initial /me shows no profile yet + default settings summary
    me0 = await client.get("/api/v1/dropshipper/me", headers=cust_headers)
    assert me0.status_code == 200, me0.text
    assert me0.json()["profile"] is None
    assert me0.json()["settings"]["enabled"] is True

    # Upload shop logo via /profile/upload
    upload = await client.post(
        "/api/v1/dropshipper/profile/upload",
        headers=cust_headers,
        files={"file": ("logo.png", io.BytesIO(_MINIMAL_PNG), "image/png")},
        data={"field": "shop_logo"},
    )
    assert upload.status_code == 200, upload.text
    logo_url = upload.json()["url"]
    assert logo_url.startswith("/media/dropshippers/")

    # Submit KYC application
    apply_payload = {
        "shop_name": "Dhaka Fashion Hub",
        "shop_phone": "01711223344",
        "shop_logo_url": logo_url,
        "shop_address": "Mirpur 10, Dhaka",
        "business_url": "https://fb.com/dhakafashionhub",
        "nid_number": "1234567890",
        "payout_method": "bkash",
        "payout_account_number": "01711223344",
        "payout_account_name": "Rafiqul Islam",
    }
    applied = await client.post(
        "/api/v1/dropshipper/apply", headers=cust_headers, json=apply_payload
    )
    assert applied.status_code == 201, applied.text
    profile_id = applied.json()["id"]
    assert applied.json()["status"] == "pending"
    assert applied.json()["shop_slug"] == "dhaka-fashion-hub"

    # Pending applicant cannot access /catalog
    pending_cat = await client.get("/api/v1/dropshipper/catalog", headers=cust_headers)
    assert pending_cat.status_code == 403

    # Admin rejects -> applicant can re-apply
    rej = await client.post(
        f"/api/v1/admin/dropshipping/partners/{profile_id}/reject",
        headers=auth_headers,
        json={"reason": "NID photo blurry"},
    )
    assert rej.status_code == 200, rej.text
    assert rej.json()["status"] == "rejected"
    assert rej.json()["rejection_reason"] == "NID photo blurry"

    reapplied = await client.post(
        "/api/v1/dropshipper/apply",
        headers=cust_headers,
        json={**apply_payload, "nid_number": "9876543210"},
    )
    assert reapplied.status_code == 201, reapplied.text
    assert reapplied.json()["status"] == "pending"
    assert reapplied.json()["rejection_reason"] is None

    # Admin approves -> role upgrades customer -> dropshipper, notification + audit logged
    approved = await client.post(
        f"/api/v1/admin/dropshipping/partners/{profile_id}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["user_role"] == UserRole.DROPSHIPPER.value

    refreshed_user = await db_session.scalar(select(User).where(User.id == uuid.UUID(user_id)))
    assert refreshed_user is not None
    assert refreshed_user.role == UserRole.DROPSHIPPER.value

    notif = await db_session.scalar(
        select(CustomerNotification)
        .where(CustomerNotification.user_id == refreshed_user.id)
        .order_by(CustomerNotification.created_at.desc())
    )
    assert notif is not None
    assert "Approved" in notif.title

    audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.DROPSHIPPER_APPROVED.value,
            AuditEvent.target_id == profile_id,
        )
    )
    assert audit is not None

    # Approved partner can update profile
    patched = await client.patch(
        "/api/v1/dropshipper/profile",
        headers=cust_headers,
        json={"shop_address": "Banani, Dhaka"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["shop_address"] == "Banani, Dhaka"

    # Suspend blocks catalog; reactivate restores it
    susp = await client.post(
        f"/api/v1/admin/dropshipping/partners/{profile_id}/suspend",
        headers=auth_headers,
        json={"reason": "High RTO"},
    )
    assert susp.status_code == 200, susp.text
    assert susp.json()["status"] == "suspended"
    susp_cat = await client.get("/api/v1/dropshipper/catalog", headers=cust_headers)
    assert susp_cat.status_code == 403

    react = await client.post(
        f"/api/v1/admin/dropshipping/partners/{profile_id}/reactivate",
        headers=auth_headers,
    )
    assert react.status_code == 200, react.text
    assert react.json()["status"] == "approved"
    react_cat = await client.get("/api/v1/dropshipper/catalog", headers=cust_headers)
    assert react_cat.status_code == 200

    # Staff user applying and getting approved MUST NOT have their staff role downgraded
    staff_apply = await client.post(
        "/api/v1/dropshipper/apply",
        headers=auth_headers,
        json={**apply_payload, "shop_name": "Staff Test Shop"},
    )
    assert staff_apply.status_code == 201, staff_apply.text
    staff_pid = staff_apply.json()["id"]
    staff_approved = await client.post(
        f"/api/v1/admin/dropshipping/partners/{staff_pid}/approve",
        headers=auth_headers,
    )
    assert staff_approved.status_code == 200, staff_approved.text
    assert staff_approved.json()["user_role"] == UserRole.SUPERADMIN.value


async def test_catalog_never_leaks_cost_price_or_supplier_and_admin_settings_work(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Create a supplier + category first
    sup = await client.post(
        "/api/v1/admin/inventory/suppliers",
        headers=auth_headers,
        json={"name": "Secret Wholesale Mill", "phone": "01700000001"},
    )
    assert sup.status_code == 201, sup.text
    supplier_id = sup.json()["id"]

    cat = await client.post(
        "/api/v1/admin/categories",
        headers=auth_headers,
        data={"payload": json.dumps({"name": "Dropship Apparel", "slug": "dropship-apparel"})},
    )
    assert cat.status_code == 201, cat.text
    category_id = cat.json()["id"]

    # Product 1: Dropshipping enabled
    p1 = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        data={
            "payload": json.dumps(
                {
                    "title": "Premium Cotton Panjabi",
                    "category_id": category_id,
                    "supplier_id": supplier_id,
                    "price": 1450,
                    "cost_price": 450,
                    "quantity": 25,
                    "weight_grams": 350,
                    "allow_dropshipping": True,
                    "dropship_price": 850,
                    "min_sell_price": 1100,
                    "max_sell_price": 1800,
                    "image_src": "/media/products/panjabi-1.jpg",
                    "published": True,
                }
            )
        },
    )
    assert p1.status_code == 201, p1.text
    assert p1.json()["allow_dropshipping"] is True
    assert p1.json()["dropship_price"] == 850

    # Product 2: Retail only (allow_dropshipping=False)
    p2 = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        data={
            "payload": json.dumps(
                {
                    "title": "Retail Only Watch",
                    "category_id": category_id,
                    "supplier_id": supplier_id,
                    "price": 2200,
                    "cost_price": 900,
                    "quantity": 10,
                    "weight_grams": 200,
                    "allow_dropshipping": False,
                    "image_src": "/media/products/watch-1.jpg",
                    "published": True,
                }
            )
        },
    )
    assert p2.status_code == 201, p2.text

    # Register & approve dropshipper
    cust_headers, _ = await _register_customer(
        client, phone="01811223344", email="catalog.drop@example.com"
    )
    applied = await client.post(
        "/api/v1/dropshipper/apply",
        headers=cust_headers,
        json={
            "shop_name": "Catalog Reseller",
            "shop_phone": "01811223344",
            "payout_method": "nagad",
            "payout_account_number": "01811223344",
        },
    )
    assert applied.status_code == 201, applied.text
    approve = await client.post(
        f"/api/v1/admin/dropshipping/partners/{applied.json()['id']}/approve",
        headers=auth_headers,
    )
    assert approve.status_code == 200, approve.text

    # Query catalog
    cat_res = await client.get("/api/v1/dropshipper/catalog", headers=cust_headers)
    assert cat_res.status_code == 200, cat_res.text
    body = cat_res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["title"] == "Premium Cotton Panjabi"
    assert item["dropship_price"] == 850
    assert item["suggested_retail_price"] == 1450
    assert item["min_sell_price"] == 1100
    assert item["max_sell_price"] == 1800
    assert item["weight_grams"] == 350
    assert len(item["media"]) >= 1

    # Strict security check: cost_price and supplier_id MUST NOT appear anywhere in catalog payload
    raw_json = json.dumps(body)
    assert "cost_price" not in raw_json
    assert "supplier_id" not in raw_json
    assert supplier_id not in raw_json

    # Admin overview & settings update
    ov = await client.get("/api/v1/admin/dropshipping/overview", headers=auth_headers)
    assert ov.status_code == 200, ov.text
    assert ov.json()["approved_count"] >= 1
    assert ov.json()["catalog_products_count"] == 1

    st = await client.patch(
        "/api/v1/admin/dropshipping/settings",
        headers=auth_headers,
        json={"payout_unlock_days": 5, "min_withdrawal_amount": 1000, "rto_charge_mode": "fixed"},
    )
    assert st.status_code == 200, st.text
    assert st.json()["payout_unlock_days"] == 5
    assert st.json()["min_withdrawal_amount"] == 1000
    assert st.json()["rto_charge_mode"] == "fixed"
