"""Bulk delete: same rules as a single delete, one product at a time, partial success."""

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import product_service
from tests.test_orders import SHIPPING, _key
from tests.test_product_media import MP4
from tests.test_products import JPEG, _create, _parts, _product

ADMIN = "/api/v1/admin/products"
BULK = f"{ADMIN}/bulk"


async def _bulk(client: AsyncClient, headers: dict[str, str], ids: object):
    return await client.request("DELETE", BULK, headers=headers, json={"ids": ids})


async def test_bulk_delete_removes_products_files_and_keeps_orders(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    parts = _parts(
        _product(title="Bulk Photo Lamp", image_src=""), images=[("a.jpg", JPEG, "image/jpeg")]
    )
    parts.append(("videos", ("clip.mp4", MP4, "video/mp4")))
    with_media = await client.post(ADMIN, headers=auth_headers, files=parts)
    assert with_media.status_code == 201, with_media.text
    assert len(list((tmp_path / "products").iterdir())) == 2

    ordered = await _create(client, auth_headers, title="Bulk Ordered Gown", price=500, quantity=5)
    order = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": ordered["id"], "quantity": 1}],
            **SHIPPING,
            "district": "ঢাকা",
            "area": "ধানমন্ডি",
            "phone": "01711111111",
        },
    )
    assert order.status_code == 201, order.text
    missing = str(uuid.uuid4())

    ids = [with_media.json()["id"], ordered["id"], ordered["id"].upper(), missing]
    response = await _bulk(client, auth_headers, ids)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requested"] == 3  # the duplicate counts once
    assert body["deleted"] == 2
    assert set(body["deleted_ids"]) == {with_media.json()["id"], ordered["id"]}
    assert body["skipped"] == [
        {"id": missing, "reason": "not_found", "message": "Product not found"}
    ]
    assert body["failed"] == []

    assert (await client.get(f"{ADMIN}/{ordered['id']}", headers=auth_headers)).status_code == 404
    assert not any((tmp_path / "products").iterdir())
    kept = await client.get(f"/api/v1/admin/orders/{order.json()['id']}", headers=auth_headers)
    assert kept.status_code == 200
    # The order and its line stay. (Postgres empties the product link; SQLite has no FK action.)
    assert len(kept.json()["items"]) == 1


async def test_bulk_delete_rejects_bad_requests(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    empty = await _bulk(client, auth_headers, [])
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == "Choose at least one product to delete"

    bad = await _bulk(client, auth_headers, [str(uuid.uuid4()), "nope", 7])
    assert bad.status_code == 422
    assert bad.json()["error"]["message"] == "Some product ids are not valid"
    assert bad.json()["error"]["details"] == {"invalid_ids": ["nope", "7"]}

    many = await _bulk(client, auth_headers, [str(uuid.uuid4()) for _ in range(101)])
    assert many.status_code == 422
    assert many.json()["error"]["message"] == "Delete at most 100 products at a time"

    no_body = await client.request("DELETE", BULK, headers=auth_headers)
    assert no_body.status_code == 422


async def test_bulk_delete_needs_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Guarded Lamp")
    assert (await _bulk(client, {}, [product["id"]])).status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "bulk-viewer@implesia.com",
            "full_name": "Bulk Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "bulk-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await _bulk(client, viewer, [product["id"]])).status_code == 403
    assert (await client.get(f"{ADMIN}/{product['id']}", headers=auth_headers)).status_code == 200


async def test_one_failure_does_not_stop_the_rest(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _create(client, auth_headers, title="Bulk First Lamp")
    broken = await _create(client, auth_headers, title="Bulk Broken Lamp")
    last = await _create(client, auth_headers, title="Bulk Last Lamp")
    real_delete = product_service.delete_product

    async def flaky(db, product):  # type: ignore[no-untyped-def]
        if str(product.id) == broken["id"]:
            raise RuntimeError("disk on fire")
        await real_delete(db, product)

    monkeypatch.setattr(product_service, "delete_product", flaky)
    response = await _bulk(client, auth_headers, [first["id"], broken["id"], last["id"]])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted_ids"] == [first["id"], last["id"]]
    assert body["failed"] == [
        {"id": broken["id"], "reason": "error", "message": "The product could not be deleted"}
    ]
    assert "disk on fire" not in response.text
    assert (await client.get(f"{ADMIN}/{broken['id']}", headers=auth_headers)).status_code == 200
