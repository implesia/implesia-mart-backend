from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.site_header import SiteHeader
from app.services.site_header_defaults import DEFAULT_ITEMS

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)

PUBLIC = "/api/v1/site/header"
ADMIN = "/api/v1/admin/site/header"


def _body(**extra: object) -> dict:
    body: dict = {
        "items": [
            {"label": "Home", "href": "/", "enabled": True},
            {"label": "Hidden", "href": "/hidden", "enabled": False},
            {"label": "Shop", "href": "/products?category=gadgets", "enabled": True},
            {"label": "Mail", "href": "mailto:hi@example.com", "enabled": True},
        ]
    }
    body.update(extra)
    return body


async def test_empty_table_serves_the_previous_menu_exactly(client: AsyncClient) -> None:
    live = (await client.get(PUBLIC)).json()
    assert [(i["label"], i["href"]) for i in live["items"]] == [
        (i["label"], i["href"]) for i in DEFAULT_ITEMS
    ]
    assert [i["href"] for i in live["items"]] == [
        "/",
        "/products",
        "/about-us",
        "/sustainability",
        "/contact-us",
        "/blogs",
    ]


async def test_admin_view_flags_defaults_and_requires_auth(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    admin = await client.get(ADMIN, headers=auth_headers)
    assert admin.status_code == 200
    assert admin.json()["is_default"] is True
    assert admin.headers["cache-control"] == "no-store"


async def test_save_is_live_immediately_in_order_and_hides_disabled(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(ADMIN, headers=auth_headers, json=_body())
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_default"] is False
    assert len(saved.json()["items"]) == 4  # editors still see hidden links

    live = (await client.get(PUBLIC)).json()
    assert [i["label"] for i in live["items"]] == ["Home", "Shop", "Mail"]

    reordered = _body(items=list(reversed(_body()["items"])))
    await client.put(ADMIN, headers=auth_headers, json=reordered)
    live = (await client.get(PUBLIC)).json()
    assert [i["label"] for i in live["items"]] == ["Mail", "Shop", "Home"]


async def test_reset_restores_defaults(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await client.put(ADMIN, headers=auth_headers, json=_body())
    reset = await client.delete(ADMIN, headers=auth_headers)
    assert reset.status_code == 200 and reset.json()["is_default"] is True
    assert len((await client.get(PUBLIC)).json()["items"]) == len(DEFAULT_ITEMS)


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"label": "Off", "href": "/x", "enabled": False}],
        [{"label": "L", "href": "javascript:alert(1)"}],
        [{"label": "L", "href": "//evil.example"}],
        [{"label": "L", "href": "data:text/html,x"}],
        [{"label": "L", "href": "evil.example"}],
        [{"label": "", "href": "/x"}],
        [{"label": "<b>x</b>", "href": "/x"}],
        [{"label": "L", "href": "/x", "extra": 1}],
        [{"label": "L", "href": "/x"}] * 9,
        [{"label": "L" * 81, "href": "/x"}],
    ],
)
async def test_invalid_menus_are_rejected_with_the_error_envelope(
    client: AsyncClient, auth_headers: dict[str, str], items: list
) -> None:
    response = await client.put(ADMIN, headers=auth_headers, json={"items": items})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"]
    assert (await client.get(ADMIN, headers=auth_headers)).json()["is_default"] is True


async def test_unknown_field_is_rejected(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.put(ADMIN, headers=auth_headers, json=_body(unknown=1))
    assert response.status_code == 422


async def test_control_characters_are_stripped(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    items = [{"label": "  A\x00B  ", "href": "/x"}]
    saved = await client.put(ADMIN, headers=auth_headers, json={"items": items})
    assert saved.status_code == 200
    assert (await client.get(PUBLIC)).json()["items"][0]["label"] == "AB"


async def test_unusable_stored_values_never_reach_the_storefront(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await client.put(ADMIN, headers=auth_headers, json=_body())
    await db_session.execute(
        update(SiteHeader).values(items=[{"label": "L", "href": "javascript:x", "enabled": True}])
    )
    await db_session.commit()
    live = (await client.get(PUBLIC)).json()
    assert "javascript" not in str(live)
    assert len(live["items"]) == len(DEFAULT_ITEMS)  # corrupt row falls back to the built-in menu

    await db_session.execute(update(SiteHeader).values(items="not a list"))
    await db_session.commit()
    assert len((await client.get(PUBLIC)).json()["items"]) == len(DEFAULT_ITEMS)

    await db_session.execute(
        update(SiteHeader).values(items=[{"label": "Off", "href": "/x", "enabled": False}])
    )
    await db_session.commit()
    assert len((await client.get(PUBLIC)).json()["items"]) == len(DEFAULT_ITEMS)


async def test_viewers_cannot_edit_but_the_public_can_read(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.put(ADMIN, json=_body())).status_code == 401
    assert (await client.delete(ADMIN)).status_code == 401
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "header-viewer@implesia.com",
            "full_name": "Header Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "header-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.put(ADMIN, headers=viewer, json=_body())).status_code == 403
    assert (await client.delete(ADMIN, headers=viewer)).status_code == 403
    assert (await client.get(ADMIN, headers=viewer)).status_code == 403
    assert (await client.get(PUBLIC)).status_code == 200


async def test_default_header_has_no_custom_logo(client: AsyncClient) -> None:
    live = (await client.get(PUBLIC)).json()
    assert live["logo_src"] == "" and live["logo_alt"] == ""


@pytest.mark.parametrize(
    "extra",
    [
        {"logo_src": "javascript:alert(1)", "logo_alt": "x"},
        {"logo_src": "/media/header/a.jpg", "logo_alt": ""},
        {"logo_src": "/media/header/a.jpg", "logo_alt": "<b>x</b>"},
    ],
)
async def test_bad_logo_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str], extra: dict
) -> None:
    res = await client.put(ADMIN, headers=auth_headers, json=_body(**extra))
    assert res.status_code == 422


async def test_logo_upload_save_replace_and_reset(
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
    assert url.startswith("/media/header/") and url.endswith(".jpg")
    stored = tmp_path / "header" / url.rsplit("/", 1)[1]
    assert stored.read_bytes() == JPEG

    bad = await client.post(
        f"{ADMIN}/logo",
        headers=auth_headers,
        files={"image": ("l.png", b"<html>1</html>", "image/png")},
    )
    assert bad.status_code == 422

    saved = await client.put(
        ADMIN, headers=auth_headers, json=_body(logo_src=url, logo_alt="Shop logo")
    )
    assert saved.status_code == 200, saved.text
    live = (await client.get(PUBLIC)).json()
    assert live["logo_src"] == url and live["logo_alt"] == "Shop logo"

    # Saving the menu again without a logo removes the old owned file.
    await client.put(ADMIN, headers=auth_headers, json=_body())
    assert not stored.exists()
    assert (await client.get(PUBLIC)).json()["logo_src"] == ""

    # Reset also removes an owned logo.
    again = (await client.post(f"{ADMIN}/logo", headers=auth_headers, files=files)).json()["url"]
    await client.put(ADMIN, headers=auth_headers, json=_body(logo_src=again, logo_alt="L"))
    kept = tmp_path / "header" / again.rsplit("/", 1)[1]
    assert kept.exists()
    reset = await client.delete(ADMIN, headers=auth_headers)
    assert reset.json()["logo_src"] == ""
    assert not kept.exists()


async def test_unusable_stored_logo_never_reaches_the_storefront(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await client.put(ADMIN, headers=auth_headers, json=_body())
    await db_session.execute(
        update(SiteHeader).values(logo_src="javascript:alert(1)", logo_alt="x")
    )
    await db_session.commit()
    live = (await client.get(PUBLIC)).json()
    assert live["logo_src"] == "" and "javascript" not in str(live)
    admin = (await client.get(ADMIN, headers=auth_headers)).json()
    assert admin["logo_needs_upload"] is True
