from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.site_footer import SiteFooter
from app.schemas.site_footer import link_ref_ok
from app.services.site_footer_defaults import DEFAULTS

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
PUBLIC = "/api/v1/site/footer"
ADMIN = "/api/v1/admin/site/footer"


def _body(**extra: object) -> dict:
    body: dict = {
        "brand_name": "Shop",
        "description": "About us",
        "logo_src": "",
        "logo_alt": "",
        "address": "Dhaka, Bangladesh",
        "copyright_text": "© {year} Shop",
        "show_contact": True,
        "show_social": True,
        "show_whatsapp_cta": True,
        "sections": [
            {
                "title": "Help",
                "enabled": True,
                "links": [
                    {"label": "FAQ", "href": "/faqs", "enabled": True},
                    {"label": "Hidden", "href": "/hidden", "enabled": False},
                ],
            },
            {"title": "Off", "enabled": False, "links": [{"label": "X", "href": "/x"}]},
            {"title": "Empty", "enabled": True, "links": []},
        ],
        "trust_points": [{"icon": "payments", "label": "COD", "enabled": True}],
        "legal_links": [{"label": "Privacy", "href": "/privacy-policy"}],
    }
    body.update(extra)
    return body


@pytest.mark.parametrize(
    ("href", "ok"),
    [
        ("/products?category=gadgets", True),
        ("https://example.com/a", True),
        ("http://example.com", True),
        ("mailto:hi@example.com", True),
        ("MAILTO:hi@example.com?subject=Hi", True),
        ("tel:+8801700000000", True),
        ("", False),
        ("javascript:alert(1)", False),
        ("JaVaScRiPt:alert(1)", False),
        ("data:text/html,x", False),
        ("blob:http://x/y", False),
        ("file:///etc/passwd", False),
        ("//evil.example", False),
        ("evil.example", False),
        ("/a b", False),
        ("/a\nb", False),
        ("/../x", False),
        ("mailto:not-an-email", False),
        ("tel:abc", False),
        ("https://", False),
        ("/" + "a" * 260, False),
    ],
)
def test_link_ref_ok(href: str, ok: bool) -> None:
    assert link_ref_ok(href) is ok


async def test_empty_table_serves_the_previous_footer_exactly(client: AsyncClient) -> None:
    live = (await client.get(PUBLIC)).json()
    assert live["brand_name"] == DEFAULTS["brand_name"]
    assert live["description"] == DEFAULTS["description"]
    assert live["copyright_text"] == DEFAULTS["copyright_text"]
    assert [s["title"] for s in live["sections"]] == ["Shop", "Company", "Support"]
    assert [len(s["links"]) for s in live["sections"]] == [4, 4, 5]
    assert len(live["trust_points"]) == 3 and len(live["legal_links"]) == 4
    assert live["address"] == "" and live["logo_src"] == ""


async def test_admin_view_flags_defaults_and_requires_auth(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    admin = await client.get(ADMIN, headers=auth_headers)
    assert admin.status_code == 200
    assert admin.json()["is_default"] is True
    assert admin.headers["cache-control"] == "no-store"


async def test_save_is_live_immediately_and_hides_disabled_items(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(ADMIN, headers=auth_headers, json=_body())
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_default"] is False
    assert len(saved.json()["sections"]) == 3  # editors still see everything

    live = (await client.get(PUBLIC)).json()
    assert live["brand_name"] == "Shop" and live["address"] == "Dhaka, Bangladesh"
    assert [s["title"] for s in live["sections"]] == ["Help"]
    assert [link["label"] for link in live["sections"][0]["links"]] == ["FAQ"]
    assert live["legal_links"][0]["href"] == "/privacy-policy"

    # A second save replaces the first: no stale value survives.
    await client.put(ADMIN, headers=auth_headers, json=_body(brand_name="Renamed"))
    assert (await client.get(PUBLIC)).json()["brand_name"] == "Renamed"


async def test_order_is_the_saved_order_and_cleared_lists_stay_cleared(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    sections = [
        {"title": t, "enabled": True, "links": [{"label": t, "href": "/" + t.lower()}]}
        for t in ("Zed", "Alpha", "Mid")
    ]
    await client.put(ADMIN, headers=auth_headers, json=_body(sections=sections, trust_points=[]))
    live = (await client.get(PUBLIC)).json()
    assert [s["title"] for s in live["sections"]] == ["Zed", "Alpha", "Mid"]
    assert live["trust_points"] == []


async def test_reset_restores_defaults(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await client.put(ADMIN, headers=auth_headers, json=_body())
    reset = await client.delete(ADMIN, headers=auth_headers)
    assert reset.status_code == 200 and reset.json()["is_default"] is True
    assert (await client.get(PUBLIC)).json()["brand_name"] == DEFAULTS["brand_name"]


@pytest.mark.parametrize(
    "extra",
    [
        {"brand_name": ""},
        {"brand_name": "<b>x</b>"},
        {"description": "<script>alert(1)</script>"},
        {"address": "a > b"},
        {"copyright_text": ""},
        {"logo_src": "javascript:alert(1)"},
        {"logo_src": "/media/footer/a.jpg", "logo_alt": ""},
        {"unknown": 1},
        {"description": "x" * 401},
        {"sections": [{"title": "T", "links": [{"label": "L", "href": "javascript:alert(1)"}]}]},
        {"sections": [{"title": "T", "links": [{"label": "L", "href": "//evil.example"}]}]},
        {"sections": [{"title": "<i>", "links": []}]},
        {"sections": [{"title": "T", "links": [{"label": "<b>", "href": "/x"}]}]},
        {"sections": [{"title": "T", "links": [{"label": "", "href": "/x"}]}]},
        {"sections": [{"title": "T", "links": [], "extra": 1}]},
        {"sections": [{"title": "T", "links": []}] * 9},
        {"sections": [{"title": "T", "links": [{"label": "L", "href": "/x"}] * 13}]},
        {"trust_points": [{"icon": "Bad Icon", "label": "x"}]},
        {"trust_points": [{"icon": "ok", "label": "<x>"}]},
        {"legal_links": [{"label": "L", "href": "data:text/html,x"}]},
    ],
)
async def test_invalid_footers_are_rejected_with_the_error_envelope(
    client: AsyncClient, auth_headers: dict[str, str], extra: dict
) -> None:
    response = await client.put(ADMIN, headers=auth_headers, json=_body(**extra))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"]
    assert (await client.get(ADMIN, headers=auth_headers)).json()["is_default"] is True


async def test_control_characters_are_stripped(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(ADMIN, headers=auth_headers, json=_body(description="  A\x00B  "))
    assert saved.status_code == 200
    assert (await client.get(PUBLIC)).json()["description"] == "AB"


async def test_unusable_stored_values_never_reach_the_storefront(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await client.put(ADMIN, headers=auth_headers, json=_body())
    await db_session.execute(
        update(SiteFooter).values(
            logo_src="javascript:alert(1)",
            sections=[{"title": "T", "links": [{"label": "L", "href": "javascript:x"}]}],
            legal_links="not a list",
        )
    )
    await db_session.commit()
    live = (await client.get(PUBLIC)).json()
    assert live["logo_src"] == ""
    assert len(live["sections"]) == 3  # corrupt list falls back to the built-in default
    assert len(live["legal_links"]) == 4
    assert "javascript" not in str(live)
    admin = (await client.get(ADMIN, headers=auth_headers)).json()
    assert admin["logo_needs_upload"] is True


async def test_blank_stored_brand_falls_back(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await client.put(ADMIN, headers=auth_headers, json=_body())
    await db_session.execute(update(SiteFooter).values(brand_name="", copyright_text=""))
    await db_session.commit()
    live = (await client.get(PUBLIC)).json()
    assert live["brand_name"] == DEFAULTS["brand_name"]
    assert live["copyright_text"] == DEFAULTS["copyright_text"]


async def test_viewers_cannot_edit_but_the_public_can_read(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.put(ADMIN, json=_body())).status_code == 401
    assert (await client.delete(ADMIN)).status_code == 401
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "footer-viewer@implesia.com",
            "full_name": "Footer Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "footer-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.put(ADMIN, headers=viewer, json=_body())).status_code == 403
    assert (await client.delete(ADMIN, headers=viewer)).status_code == 403
    assert (await client.get(PUBLIC)).status_code == 200


async def test_logo_upload_validates_by_content_and_serves_the_stored_path(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    files = {"image": ("l.jpg", JPEG, "image/jpeg")}
    assert (await client.post(f"{ADMIN}/logo", files=files)).status_code == 401
    ok = await client.post(f"{ADMIN}/logo", headers=auth_headers, files=files)
    assert ok.status_code == 201, ok.text
    url = ok.json()["url"]
    assert url.startswith("/media/footer/") and url.endswith(".jpg")
    assert (tmp_path / "footer" / url.rsplit("/", 1)[1]).read_bytes() == JPEG

    bad = await client.post(
        f"{ADMIN}/logo",
        headers=auth_headers,
        files={"image": ("l.png", b"<html>1</html>", "image/png")},
    )
    assert bad.status_code == 422

    saved = await client.put(
        ADMIN, headers=auth_headers, json=_body(logo_src=url, logo_alt="Shop logo")
    )
    assert saved.status_code == 200
    assert (await client.get(PUBLIC)).json()["logo_src"] == url

    # Replacing the logo removes the old owned file.
    await client.put(ADMIN, headers=auth_headers, json=_body())
    assert not (tmp_path / "footer" / url.rsplit("/", 1)[1]).exists()
