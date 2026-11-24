"""Phase 13 tests: Admin review management APIs, moderation, audit logs, and RBAC."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.audit_event import AuditEvent
from app.models.product import Product, StockStatus
from app.models.review import ProductReview
from app.models.user import User, UserRole
from app.services import refresh_token_service


@pytest.mark.asyncio
async def test_admin_reviews_overview_list_by_product_moderate_and_rbac(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    # Seed users: viewer, editor, customer
    customer = User(
        full_name="Ayesha Rahman",
        phone="01755001122",
        email="ayesha@example.com",
        password_hash=hash_password("customer-passphrase"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    viewer = User(
        full_name="Review Viewer",
        email="rev-viewer@implesia.com",
        password_hash=hash_password("viewer-passphrase"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    editor = User(
        full_name="Review Editor",
        email="rev-editor@implesia.com",
        password_hash=hash_password("editor-passphrase"),
        role=UserRole.EDITOR,
        is_active=True,
    )
    p1 = Product(
        title="Wireless Earbuds Pro",
        slug=f"earbuds-pro-{uuid.uuid4().hex[:6]}",
        price=2200,
        status=StockStatus.AVAILABLE.value,
        image_src="/media/products/earbuds.jpg",
        content={},
        published=True,
    )
    p2 = Product(
        title="Smart Watch Ultra",
        slug=f"smart-watch-{uuid.uuid4().hex[:6]}",
        price=3500,
        status=StockStatus.AVAILABLE.value,
        image_src="/media/products/watch.jpg",
        content={},
        published=True,
    )
    db_session.add_all([customer, viewer, editor, p1, p2])
    await db_session.commit()
    await db_session.refresh(customer)
    await db_session.refresh(viewer)
    await db_session.refresh(editor)
    await db_session.refresh(p1)
    await db_session.refresh(p2)

    p1_id = p1.id

    r1 = ProductReview(
        product_id=p1.id,
        user_id=customer.id,
        rating=5,
        headline="Amazing sound quality",
        comment="Battery lasts all day and bass is crisp.",
        is_verified_purchase=True,
        is_published=True,
    )
    r2 = ProductReview(
        product_id=p2.id,
        user_id=customer.id,
        rating=3,
        headline="Decent watch",
        comment="Good screen, strap could be softer.",
        is_verified_purchase=True,
        is_published=False,
    )
    db_session.add_all([r1, r2])
    await db_session.commit()
    await db_session.refresh(r1)
    await db_session.refresh(r2)
    r1_id, r2_id = r1.id, r2.id

    cust_tok = await refresh_token_service.issue_session(db_session, customer)
    view_tok = await refresh_token_service.issue_session(db_session, viewer)
    edit_tok = await refresh_token_service.issue_session(db_session, editor)
    cust_headers = {"Authorization": f"Bearer {cust_tok.access_token}"}
    view_headers = {"Authorization": f"Bearer {view_tok.access_token}"}
    edit_headers = {"Authorization": f"Bearer {edit_tok.access_token}"}

    # 1. Customer is blocked from admin review endpoints
    assert (
        await client.get("/api/v1/admin/reviews/overview", headers=cust_headers)
    ).status_code == 403
    assert (await client.get("/api/v1/admin/reviews", headers=cust_headers)).status_code == 403
    assert (
        await client.get("/api/v1/admin/reviews/by-product", headers=cust_headers)
    ).status_code == 403

    # 2. Viewer can read overview, list, and by-product
    ov = await client.get("/api/v1/admin/reviews/overview", headers=view_headers)
    assert ov.status_code == 200, ov.text
    ov_data = ov.json()
    assert ov_data["total_reviews"] == 2
    assert ov_data["published_count"] == 1
    assert ov_data["hidden_count"] == 1
    assert ov_data["average_rating"] == 4.0
    assert ov_data["five_star_percent"] == 50.0
    assert ov_data["products_with_reviews_count"] == 2
    assert ov_data["rating_distribution"]["5"] == 1
    assert ov_data["rating_distribution"]["3"] == 1
    assert len(ov_data["recent_reviews"]) == 2

    # 3. List with filters & search
    filtered = await client.get(
        f"/api/v1/admin/reviews?product_id={p1_id}&rating=5&is_published=true&q=earbuds",
        headers=view_headers,
    )
    assert filtered.status_code == 200, filtered.text
    f_data = filtered.json()
    assert f_data["total"] == 1
    assert f_data["items"][0]["product"]["name"] == "Wireless Earbuds Pro"
    assert f_data["items"][0]["product"]["thumbnail"] == "/media/products/earbuds.jpg"
    assert f_data["items"][0]["customer"]["full_name"] == "Ayesha Rahman"

    # 4. By-product summary with search
    by_prod = await client.get("/api/v1/admin/reviews/by-product?q=Watch", headers=view_headers)
    assert by_prod.status_code == 200, by_prod.text
    bp_data = by_prod.json()
    assert bp_data["total"] == 1
    assert bp_data["items"][0]["name"] == "Smart Watch Ultra"
    assert bp_data["items"][0]["hidden_count"] == 1

    # 5. Viewer cannot PATCH or DELETE
    assert (
        await client.patch(
            f"/api/v1/admin/reviews/{r1_id}",
            headers=view_headers,
            json={"is_published": False},
        )
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/admin/reviews/{r1_id}", headers=view_headers)
    ).status_code == 403

    # 6. Editor can PATCH (edit + visibility toggle) and audit event is recorded
    patched = await client.patch(
        f"/api/v1/admin/reviews/{r2_id}",
        headers=edit_headers,
        json={"rating": 4, "headline": "Updated headline", "is_published": True},
    )
    assert patched.status_code == 200, patched.text
    p_data = patched.json()
    assert p_data["rating"] == 4
    assert p_data["headline"] == "Updated headline"
    assert p_data["is_published"] is True

    # 7. Editor can DELETE and audit event is recorded
    deleted = await client.delete(f"/api/v1/admin/reviews/{r1_id}", headers=edit_headers)
    assert deleted.status_code == 204

    events = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.target_type == "product_review")
        )
    ).all()
    actions = {ev.action for ev in events}
    assert "REVIEW_UPDATED" in actions
    assert "REVIEW_DELETED" in actions

    # Superadmin check still works cleanly
    after_list = await client.get("/api/v1/admin/reviews", headers=auth_headers)
    assert after_list.status_code == 200
    assert after_list.json()["total"] == 1
