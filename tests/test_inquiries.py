import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import inquiries as inquiries_endpoint
from app.models.audit_event import AuditEvent
from app.models.inquiry import Inquiry
from app.rate_limit import limiter
from app.schemas.inquiry import EMAIL_MESSAGE, EMPTY_MESSAGE, PHONE_MESSAGE

URL = "/api/v1/inquiries"
ADMIN = "/api/v1/admin/inquiries"


async def _count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(Inquiry))).scalar_one())


async def _submit(client: AsyncClient, **body: object) -> dict[str, object]:
    response = await client.post(URL, json={"elapsed_ms": 5000, **body})
    assert response.status_code == 201, response.text
    return response.json()


async def test_partial_submission_is_normalised_and_returns_only_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = await _submit(
        client,
        type="contact",
        email="  QA.Person@Example.COM ",
        phone="+880 ১৭১২-৩৪৫৬৭৮",
        name="  QA   Tester ",
        message="  <b>hi</b>\r\nsecond line  ",
        meta={"page_path": "/contact-us", "topic": "ডেলিভারি", "ip": "1.2.3.4", "cookie": "x"},
    )
    assert set(body) == {"id", "status"} and body["status"] == "received"
    row = await db_session.scalar(
        select(Inquiry).where(Inquiry.public_id == uuid.UUID(str(body["id"])))
    )
    assert row is not None
    assert row.email == "qa.person@example.com"
    assert row.phone == "01712345678"
    assert row.name == "QA Tester"
    assert row.message == "<b>hi</b>\nsecond line"  # stored as plain text, escaped on render
    assert row.meta == {"page_path": "/contact-us", "topic": "ডেলিভারি"}  # unknown keys dropped
    assert row.status == "new"


async def test_only_a_message_or_only_a_phone_is_enough(client: AsyncClient) -> None:
    await _submit(client, message="QA just a question")
    await _submit(client, phone="01812345678")


async def test_fully_empty_submission_gets_a_friendly_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for body in ({}, {"name": "QA only a name", "subject": "x"}, {"email": "   ", "message": " "}):
        response = await client.post(URL, json=body)
        assert response.status_code == 422
        assert response.json()["error"]["message"] == EMPTY_MESSAGE
    assert await _count(db_session) == 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("email", "nope", EMAIL_MESSAGE), ("phone", "12345", PHONE_MESSAGE)],
)
async def test_invalid_contact_fields_are_rejected(
    client: AsyncClient, field: str, value: str, message: str
) -> None:
    response = await client.post(URL, json={field: value, "message": "QA"})
    assert response.status_code == 422
    assert message in response.text


async def test_unknown_fields_and_long_text(client: AsyncClient, db_session: AsyncSession) -> None:
    extra = await client.post(URL, json={"message": "QA", "status": "resolved"})
    assert extra.status_code == 422
    await _submit(client, message="x" * 5000, name="n" * 500)
    row = await db_session.scalar(select(Inquiry))
    assert row is not None and len(row.message) == 2000 and len(row.name) == 80


async def test_honeypot_and_instant_posts_are_dropped_silently(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    bot = await client.post(URL, json={"message": "QA spam", "website": "http://spam"})
    fast = await client.post(URL, json={"message": "QA spam", "elapsed_ms": 200})
    assert bot.status_code == fast.status_code == 201
    assert bot.json()["status"] == "received"
    assert await _count(db_session) == 0


async def test_idempotency_key_and_newsletter_dedupe(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    first = await client.post(URL, json={"message": "QA once"}, headers=headers)
    again = await client.post(URL, json={"message": "QA once"}, headers=headers)
    assert first.json()["id"] == again.json()["id"]
    one = await _submit(client, type="newsletter", email="qa-news@example.com")
    two = await _submit(client, type="newsletter", email="QA-NEWS@example.com")
    assert one["id"] == two["id"]
    assert await _count(db_session) == 2


@pytest.fixture
def inquiry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(limiter, "_limiter", FixedWindowRateLimiter(MemoryStorage()))
    monkeypatch.setattr(inquiries_endpoint, "_INQUIRY_LIMIT", parse("2/hour"))


async def test_rate_limit_per_ip_and_replays_are_free(
    client: AsyncClient, inquiry_limit: None
) -> None:
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    await client.post(URL, json={"message": "QA 1"}, headers=headers)
    for _ in range(3):  # replays of the same key do not count
        assert (
            await client.post(URL, json={"message": "QA 1"}, headers=headers)
        ).status_code == 201
    assert (await client.post(URL, json={"message": "QA 2"})).status_code == 201
    limited = await client.post(URL, json={"message": "QA 3"})
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


def test_rate_limit_bucket_never_contains_the_raw_ip() -> None:
    class _Req:
        headers: dict[str, str] = {}
        client = type("C", (), {"host": "203.0.113.9"})()

    name, key = inquiries_endpoint._bucket(_Req())  # type: ignore[arg-type]
    assert name == "inquiries" and "203.0.113.9" not in key and len(key) == 32


async def _viewer(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, str]:
    await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "inq-viewer@implesia.com",
            "full_name": "Inq Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "inq-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_admin_routes_need_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    some = uuid.uuid4()
    for method, path in (
        ("get", ADMIN),
        ("get", f"{ADMIN}/counts"),
        ("get", f"{ADMIN}/{some}"),
        ("patch", f"{ADMIN}/{some}"),
        ("delete", f"{ADMIN}/{some}"),
    ):
        assert (
            await client.request(method.upper(), path, json={} if method == "patch" else None)
        ).status_code == 401
    viewer = await _viewer(client, auth_headers)
    assert (await client.get(ADMIN, headers=viewer)).status_code == 403
    assert (
        await client.patch(f"{ADMIN}/{some}", headers=viewer, json={"status": "resolved"})
    ).status_code == 403


async def test_list_search_filter_sort_paginate(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    for i in range(25):
        await _submit(
            client,
            type="newsletter" if i % 5 == 0 else "contact",
            email=f"qa{i:02d}@example.com",
            subject=f"QA subject {i:02d}",
            message="QA body",
        )
    await _submit(client, name="Needle Person", message="QA find me", phone="01912345678")

    # One test transaction shares now(); spread the rows out in submission order.
    base = datetime(2026, 10, 1, tzinfo=UTC)
    rows = (await db_session.execute(select(Inquiry))).scalars().all()
    for row in rows:
        rank = 99 if row.name == "Needle Person" else int(row.email[2:4])
        row.created_at = base + timedelta(minutes=rank)
    await db_session.commit()

    page1 = (await client.get(ADMIN, headers=auth_headers, params={"page_size": 10})).json()
    assert page1["total"] == 26 and page1["pages"] == 3 and len(page1["items"]) == 10
    assert page1["items"][0]["name"] == "Needle Person"  # newest first
    page3 = (
        await client.get(ADMIN, headers=auth_headers, params={"page_size": 10, "page": 3})
    ).json()
    assert len(page3["items"]) == 6
    oldest = (
        await client.get(ADMIN, headers=auth_headers, params={"sort": "oldest", "page_size": 1})
    ).json()
    assert oldest["items"][0]["email"] == "qa00@example.com"

    for q in ("needle", "01912345678", "QA02@EXAMPLE"):
        found = (await client.get(ADMIN, headers=auth_headers, params={"q": q})).json()
        assert found["total"] == 1, q
    news = (await client.get(ADMIN, headers=auth_headers, params={"type": "newsletter"})).json()
    assert news["total"] == 5 and {i["type"] for i in news["items"]} == {"newsletter"}
    weird = await client.get(ADMIN, headers=auth_headers, params={"q": "%_"})
    assert weird.json()["total"] == 0
    dated = (
        await client.get(
            ADMIN, headers=auth_headers, params={"date_from": "2000-01-01", "date_to": "2000-01-02"}
        )
    ).json()
    assert dated["total"] == 0
    assert page1["counts"] == {"new": 26, "in_progress": 0, "resolved": 0, "total": 26}
    assert (
        await client.get(ADMIN, headers=auth_headers, params={"status": "bogus"})
    ).status_code == 422


async def test_status_note_update_detail_and_delete(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await _submit(client, message="QA handle me", email="qa-handle@example.com")
    item = (await client.get(ADMIN, headers=auth_headers)).json()["items"][0]
    updated = await client.patch(
        f"{ADMIN}/{item['id']}",
        headers=auth_headers,
        json={"status": "in_progress", "admin_note": " called back "},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["status"] == "in_progress" and body["admin_note"] == "called back"
    assert body["handled_by_id"] and body["handled_by_name"]
    detail = (await client.get(f"{ADMIN}/{item['id']}", headers=auth_headers)).json()
    assert detail["message"] == "QA handle me"
    assert (
        await client.patch(f"{ADMIN}/{item['id']}", headers=auth_headers, json={"status": "closed"})
    ).status_code == 422
    counts = (await client.get(f"{ADMIN}/counts", headers=auth_headers)).json()
    assert counts["in_progress"] == 1 and counts["new"] == 0
    audit = await db_session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.target_type == "inquiries")
    )
    assert audit == 1
    assert (await client.delete(f"{ADMIN}/{item['id']}", headers=auth_headers)).status_code == 204
    assert (await client.get(f"{ADMIN}/{item['id']}", headers=auth_headers)).status_code == 404
