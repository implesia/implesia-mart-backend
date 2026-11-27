from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.test_products import JPEG

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def test_popup_starts_disabled_and_public_returns_null(client: AsyncClient) -> None:
    res = await client.get("/api/v1/home/popup")
    assert res.status_code == 200, res.text
    assert res.json() is None


async def test_popup_admin_lifecycle_image_upload_toggle_and_cleanup(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)

    initial = await client.get("/api/v1/admin/home/popup", headers=auth_headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["is_active"] is False
    assert initial.json()["delay_seconds"] == 4
    assert initial.json()["min_scroll_px"] == 150

    # Enabling without heading or image fails validation
    empty_active = await client.put(
        "/api/v1/admin/home/popup",
        headers=auth_headers,
        json={"is_active": True, "heading": "", "image_src": ""},
    )
    assert empty_active.status_code == 422

    # Upload popup image
    up1 = await client.post(
        "/api/v1/admin/home/popup/image",
        headers=auth_headers,
        files={"image": ("offer.jpg", JPEG, "image/jpeg")},
    )
    assert up1.status_code == 201, up1.text
    img1 = up1.json()["url"]
    assert img1.startswith("/media/popup/")

    # Enable popup with coupon, CTA, custom 5s delay & 200px scroll
    saved = await client.put(
        "/api/v1/admin/home/popup",
        headers=auth_headers,
        json={
            "is_active": True,
            "badge_text": "FLASH SALE",
            "heading": "Flat 15% Off Today!",
            "body": "Use this code at checkout for instant savings.",
            "coupon_code": "SAVE15",
            "cta_label": "Shop Deals",
            "cta_href": "/products?view=featured",
            "image_src": img1,
            "image_alt": "Flash sale banner",
            "delay_seconds": 5,
            "min_scroll_px": 200,
            "dismiss_cooldown_hours": 24,
            "show_on_all_pages": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_active"] is True

    # Public endpoint returns live popup
    pub = await client.get("/api/v1/home/popup")
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert body["heading"] == "Flat 15% Off Today!"
    assert body["coupon_code"] == "SAVE15"
    assert body["delay_seconds"] == 5
    assert body["min_scroll_px"] == 200
    assert body["image_src"] == img1
    assert body["version"]

    # Replace image -> old file is cleaned up from disk
    up2 = await client.post(
        "/api/v1/admin/home/popup/image",
        headers=auth_headers,
        files={"image": ("offer2.png", PNG, "image/png")},
    )
    assert up2.status_code == 201
    img2 = up2.json()["url"]
    base_payload = {k: v for k, v in saved.json().items() if k != "image_needs_upload"}
    replaced = await client.put(
        "/api/v1/admin/home/popup",
        headers=auth_headers,
        json={**base_payload, "image_src": img2},
    )
    assert replaced.status_code == 200, replaced.text
    popup_files = {p.name for p in (tmp_path / "popup").iterdir()}
    assert img1.rsplit("/", 1)[1] not in popup_files
    assert img2.rsplit("/", 1)[1] in popup_files

    # Turn OFF popup -> public immediately returns null
    replaced_payload = {k: v for k, v in replaced.json().items() if k != "image_needs_upload"}
    disabled = await client.put(
        "/api/v1/admin/home/popup",
        headers=auth_headers,
        json={**replaced_payload, "is_active": False},
    )
    assert disabled.status_code == 200
    assert (await client.get("/api/v1/home/popup")).json() is None


async def test_popup_admin_requires_cms_write_permission(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/admin/home/popup")).status_code == 401
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "popup-viewer@implesia.com",
            "full_name": "Popup Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "popup-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.put(
        "/api/v1/admin/home/popup",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"is_active": False},
    )
    assert denied.status_code == 403
