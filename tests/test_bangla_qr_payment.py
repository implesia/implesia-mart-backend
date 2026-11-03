import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.payment_service import advance_options, advance_split
from tests.test_orders import SHIPPING
from tests.test_products import _create
from tests.test_site_footer import JPEG

PUBLIC = "/api/v1/site/payment"
ADMIN = "/api/v1/admin/site/payment"


def _key() -> str:
    return uuid.uuid4().hex


async def _upload(client: AsyncClient, headers: dict[str, str]) -> str:
    files = {"image": ("qr.jpg", JPEG, "image/jpeg")}
    response = await client.post(f"{ADMIN}/qr", headers=headers, files=files)
    assert response.status_code == 200, response.text
    src = response.json()["bangla_qr_src"]
    assert src.startswith("/media/payment/")
    return src


def _order(product_id: str, **extra: object) -> dict:
    return {
        "source": "direct",
        "items": [{"product_id": product_id, "quantity": 1}],
        **SHIPPING,
        "district": "ঢাকা",
        **extra,
    }


@pytest.mark.parametrize(
    ("total", "percent", "advance", "due"),
    [
        (1001, 25, 251, 750),  # 250.25 rounds up
        (1001, 50, 501, 500),
        (1001, 75, 751, 250),
        (1001, 100, 1001, 0),
        (1000, 25, 250, 750),
        (0, 50, 0, 0),
    ],
)
def test_advance_split_rounds_up_to_whole_taka(
    total: int, percent: int, advance: int, due: int
) -> None:
    assert advance_split(total, percent) == (advance, due)


def test_advance_options_cover_the_four_percents() -> None:
    assert [option.percent for option in advance_options(400)] == [25, 50, 75, 100]


async def test_qr_upload_replace_delete_is_live_and_admin_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    empty = await client.get(PUBLIC)
    assert empty.status_code == 200
    assert empty.json() == {"bangla_qr_src": None, "bangla_qr_enabled": False}
    assert "no-store" in empty.headers.get("cache-control", "")

    files = {"image": ("qr.jpg", JPEG, "image/jpeg")}
    assert (await client.post(f"{ADMIN}/qr", files=files)).status_code == 401
    bad = await client.post(
        f"{ADMIN}/qr",
        headers=auth_headers,
        files={"image": ("qr.png", b"<html>1</html>", "image/png")},
    )
    assert bad.status_code == 422

    first = await _upload(client, auth_headers)
    public = (await client.get(PUBLIC)).json()
    assert public == {"bangla_qr_src": first, "bangla_qr_enabled": True}

    second = await _upload(client, auth_headers)
    assert second != first
    assert (await client.get(PUBLIC)).json()["bangla_qr_src"] == second
    assert not (tmp_path / "payment" / first.rsplit("/", 1)[1]).exists()

    assert (await client.delete(f"{ADMIN}/qr")).status_code == 401
    removed = await client.delete(f"{ADMIN}/qr", headers=auth_headers)
    assert removed.status_code == 200
    assert removed.json()["bangla_qr_enabled"] is False
    assert (await client.get(PUBLIC)).json()["bangla_qr_src"] is None
    assert not (tmp_path / "payment" / second.rsplit("/", 1)[1]).exists()


async def test_bangla_qr_is_refused_while_no_qr_is_set(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=3)
    quote = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "ঢাকা",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert quote.status_code == 200, quote.text
    assert quote.json()["bangla_qr_options"] == []

    refused = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(
            product["id"],
            payment_method="bangla_qr",
            advance_percent=50,
            payment_reference="TXN12345",
        ),
    )
    assert refused.status_code == 422
    assert "Bangla QR" in refused.text


async def test_bangla_qr_order_stores_the_server_split(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    await _upload(client, auth_headers)
    product = await _create(client, auth_headers, price=1001, quantity=5)

    quote = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "district": "ঢাকা",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    body = quote.json()
    total = body["total"]
    options = {option["percent"]: option for option in body["bangla_qr_options"]}
    assert sorted(options) == [25, 50, 75, 100]
    assert options[25]["advance"] == -(-total * 25 // 100)
    assert options[25]["advance"] + options[25]["due"] == total

    # Bad inputs: unknown percent, missing reference, COD carrying QR fields, client amounts.
    for extra in (
        {"payment_method": "bangla_qr", "advance_percent": 30, "payment_reference": "TXN1234"},
        {"payment_method": "bangla_qr", "advance_percent": 50, "payment_reference": ""},
        {"payment_method": "bangla_qr", "advance_percent": 50, "payment_reference": "<b>"},
        {"payment_method": "bangla_qr", "payment_reference": "TXN1234"},
        {"payment_method": "cod", "advance_percent": 50},
        {"payment_method": "card"},
        {
            "payment_method": "bangla_qr",
            "advance_percent": 50,
            "payment_reference": "TXN1234",
            "advance_amount": 1,
        },
    ):
        rejected = await client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": _key()},
            json=_order(product["id"], **extra),
        )
        assert rejected.status_code == 422, (extra, rejected.text)

    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(
            product["id"],
            payment_method="bangla_qr",
            advance_percent=25,
            payment_reference=" 017 1234 5678 ",
        ),
    )
    assert placed.status_code == 201, placed.text
    order = placed.json()
    assert order["total"] == total
    assert order["payment_method"] == "bangla_qr"
    assert order["advance_percent"] == 25
    assert order["advance_amount"] == options[25]["advance"]
    assert order["due_amount"] == total - options[25]["advance"]
    assert order["payment_reference"] == "01712345678"

    admin = await client.get(f"/api/v1/admin/orders/{order['id']}", headers=auth_headers)
    assert admin.status_code == 200, admin.text
    detail = admin.json()
    assert detail["payment_method"] == "bangla_qr"
    assert detail["advance_percent"] == 25
    assert detail["advance_amount"] == options[25]["advance"]
    assert detail["due_amount"] == order["due_amount"]
    assert detail["payment_reference"] == "01712345678"


async def test_cod_orders_owe_the_whole_total(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=700, quantity=2)
    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(product["id"]),
    )
    assert placed.status_code == 201, placed.text
    order = placed.json()
    assert order["payment_method"] == "cod"
    assert order["advance_percent"] is None
    assert order["advance_amount"] == 0
    assert order["due_amount"] == order["total"]
