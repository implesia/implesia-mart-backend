import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.order import OrderLookup
from tests.test_orders import SHIPPING
from tests.test_products import _create


@pytest.mark.parametrize(
    "raw",
    [
        "01712345678",
        "8801712345678",
        "+8801712345678",
        "+880 1712-345678",
        "+88 01712 345 678",
        "০১৭১২৩৪৫৬৭৮",
    ],
)
def test_lookup_phone_accepts_bd_spellings(raw: str) -> None:
    lookup = OrderLookup(number="IM-0000ABCD", phone=raw)
    assert lookup.phone == "01712345678"


@pytest.mark.parametrize(
    "raw",
    [
        "01212345678",
        "+8801212345678",
        "0171234567",
        "017123456781",
        "+8811712345678",
        "abc01712345678",
    ],
)
def test_lookup_phone_rejects_invalid_numbers(raw: str) -> None:
    with pytest.raises(ValidationError):
        OrderLookup(number="IM-0000ABCD", phone=raw)


async def test_order_stores_plus_880_phone_as_local(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, price=1000, quantity=3)
    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
            "phone": "+8801712345678",
            "district": "ঢাকা",
        },
    )
    assert placed.status_code == 201, placed.text
    assert placed.json()["phone"] == "01712345678"

    found = await client.post(
        "/api/v1/orders/lookup",
        json={"number": placed.json()["number"], "phone": "880 1712-345678"},
    )
    assert found.status_code == 200, found.text

    bad = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
            "phone": "+8801212345678",
            "district": "ঢাকা",
        },
    )
    assert bad.status_code == 422
