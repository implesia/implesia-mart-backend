import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_contact import SiteContact
from app.schemas.site_contact import normalize_email, normalize_phone
from app.services import site_contact_service as service

PUBLIC = "/api/v1/site/contact"
ADMIN = "/api/v1/admin/site/contact"
NEW = {"phone": "01711223344", "whatsapp": "01811223344", "email": "Help@Example.com"}


def test_defaults_are_the_official_values() -> None:
    assert (service.DEFAULT_PHONE, service.DEFAULT_WHATSAPP) == ("01580569129", "01580569129")
    assert service.DEFAULT_EMAIL == "implesiamart@gmail.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01580569129", "01580569129"),
        ("+880 1580-569129", "01580569129"),
        ("8801580569129", "01580569129"),
        (" 0158 056 9129 ", "01580569129"),
        ("(+880)1580569129", "01580569129"),
    ],
)
def test_phone_accepts_common_spellings(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "12345", "0158056912", "01280569129", "015805691290", "abc", "tel:01580569129", "+8801"],
)
def test_phone_rejects_everything_else(raw: str) -> None:
    assert normalize_phone(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["", "x", "a@b", "a b@c.com", "a@b.com?subject=x", "a@b.com,c@d.com", "<a@b.com>", "a@@b.com"],
)
def test_email_rejects_bad_values(raw: str) -> None:
    assert normalize_email(raw) is None


async def test_public_serves_defaults_without_a_row(client: AsyncClient) -> None:
    body = (await client.get(PUBLIC)).json()
    assert body == {
        "phone": "01580569129",
        "whatsapp": "01580569129",
        "email": "implesiamart@gmail.com",
        "tel_href": "tel:+8801580569129",
        "whatsapp_href": "https://wa.me/8801580569129",
        "mailto_href": "mailto:implesiamart@gmail.com",
    }


async def test_admin_requires_an_editor(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    assert (await client.put(ADMIN, json=NEW)).status_code == 401
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "site-contact-viewer@implesia.com",
            "full_name": "Site Contact Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "site-contact-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.put(ADMIN, headers=viewer, json=NEW)).status_code == 403
    assert (await client.get(ADMIN, headers=viewer)).status_code == 403
    assert (await client.get(PUBLIC)).json()["phone"] == "01580569129"  # nothing changed


async def test_admin_view_flags_defaults_and_is_not_cached(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    admin = await client.get(ADMIN, headers=auth_headers)
    assert admin.status_code == 200
    assert admin.json()["is_default"] is True
    assert admin.headers["cache-control"] == "no-store"


async def test_save_is_live_immediately_and_normalised(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(ADMIN, headers=auth_headers, json=NEW)
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_default"] is False
    live = (await client.get(PUBLIC)).json()
    assert live["phone"] == "01711223344"
    assert live["whatsapp"] == "01811223344"
    assert live["email"] == "help@example.com"
    assert live["tel_href"] == "tel:+8801711223344"
    assert live["whatsapp_href"] == "https://wa.me/8801811223344"
    assert live["mailto_href"] == "mailto:help@example.com"

    again = await client.put(ADMIN, headers=auth_headers, json={**NEW, "phone": "+880 1911-223344"})
    assert again.json()["phone"] == "01911223344"
    assert (await client.get(PUBLIC)).json()["tel_href"] == "tel:+8801911223344"


@pytest.mark.parametrize(
    "patch",
    [
        {"phone": "12345"},
        {"phone": ""},
        {"whatsapp": "abc"},
        {"email": "not-an-email"},
        {"email": "a@b.com?bcc=x@y.com"},
        {"extra": "field"},
    ],
)
async def test_invalid_input_is_rejected_and_nothing_changes(
    client: AsyncClient, auth_headers: dict[str, str], patch: dict[str, str]
) -> None:
    response = await client.put(ADMIN, headers=auth_headers, json={**NEW, **patch})
    assert response.status_code == 422, response.text
    assert (await client.get(PUBLIC)).json()["phone"] == "01580569129"


async def test_missing_field_is_rejected(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.put(ADMIN, headers=auth_headers, json={"phone": "01711223344"})
    assert response.status_code == 422


async def test_unreadable_stored_row_falls_back_to_defaults(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await client.put(ADMIN, headers=auth_headers, json=NEW)
    await db_session.execute(update(SiteContact).values(phone="nope"))
    await db_session.commit()
    live = (await client.get(PUBLIC)).json()
    assert live["phone"] == "01580569129"


def test_rewrite_href_follows_only_whatsapp_and_tel_links() -> None:
    contact = service._public("01711223344", "01811223344", "a@b.com")
    rewrite = service.rewrite_href
    assert rewrite("https://wa.me/8801516527932", contact) == "https://wa.me/8801811223344"
    assert rewrite("https://wa.me/8801516527932?text=hi%20there", contact) == (
        "https://wa.me/8801811223344?text=hi%20there"
    )
    assert rewrite("tel:+8801516527932", contact) == "tel:+8801711223344"
    assert rewrite("tel:+880 1516-527932", contact) == "tel:+8801711223344"
    for untouched in ("/products", "mailto:x@y.com", "https://example.com/wa.me/1", ""):
        assert rewrite(untouched, contact) == untouched


async def test_central_contact_reaches_every_consumer(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Contact details channels (header, footer, floating button, contact page).
    details = {
        "is_active": True,
        "title": "Contact",
        "subtitle": "",
        "badge": "",
        "channels": [
            {"icon": "call", "title": "Call", "value": "OLD", "href": "tel:+8801516527932"},
            {
                "icon": "chat",
                "title": "WA",
                "value": "OLD",
                "href": "https://wa.me/8801516527932?text=hello",
            },
            {"icon": "mail", "title": "Mail", "value": "old@x.com", "href": "mailto:old@x.com"},
            {"icon": "location_on", "title": "Area", "value": "BD", "href": "/shipping-returns"},
        ],
        "social": [],
    }
    url = "/api/v1/admin/pages/contact/details"
    assert (await client.patch(url, headers=auth_headers, json=details)).status_code == 200
    await client.put(ADMIN, headers=auth_headers, json=NEW)

    public = (await client.get("/api/v1/pages/contact/details")).json()
    by_icon = {c["icon"]: c for c in public["channels"]}
    assert (by_icon["call"]["value"], by_icon["call"]["href"]) == (
        "01711223344",
        "tel:+8801711223344",
    )
    assert by_icon["chat"]["href"] == "https://wa.me/8801811223344?text=hello"
    assert by_icon["chat"]["value"] == "01811223344"
    assert by_icon["mail"]["href"] == "mailto:help@example.com"
    assert by_icon["location_on"]["href"] == "/shipping-returns"  # unrelated rows untouched
    admin = (await client.get(url, headers=auth_headers)).json()
    assert {c["icon"]: c["value"] for c in admin["channels"]}["call"] == "01711223344"

    # Contact hero buttons and the About "custom dress" call to action.
    hero = (await client.get("/api/v1/pages/contact/hero")).json()
    assert hero["primary_cta"]["href"].startswith("https://wa.me/8801811223344?text=")
    assert hero["secondary_cta"]["href"] == "tel:+8801711223344"
    admin_hero = (await client.get("/api/v1/admin/pages/contact/hero", headers=auth_headers)).json()
    assert admin_hero["secondary_cta"]["href"] == "tel:+8801711223344"

    dresses = (await client.get("/api/v1/pages/about/dresses")).json()["items"]
    assert dresses[0]["primary_href"].startswith("https://wa.me/8801811223344?text=")
    assert dresses[0]["secondary_href"] == "/products?category=fashion"
