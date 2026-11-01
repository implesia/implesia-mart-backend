import json
from collections.abc import Iterator
from contextlib import contextmanager

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.badge import SYSTEM_BADGES, Badge
from tests.test_products import _parts, _product

ADMIN = "/api/v1/admin/badges"
PRODUCTS = "/api/v1/admin/products"


async def _seed_system(db: AsyncSession) -> dict[str, str]:
    """Migration 0084 seeds these; the SQLite test database is built from the models."""
    rows = [
        Badge(
            name=name,
            slug=slug,
            tone="gold" if slug == "best-seller" else "primary",
            is_system=True,
        )
        for slug, name in SYSTEM_BADGES.items()
    ]
    db.add_all(rows)
    await db.commit()
    return {row.slug: str(row.id) for row in rows}


async def _badge(client: AsyncClient, headers: dict[str, str], **body: object) -> dict:
    response = await client.post(ADMIN, headers=headers, json={"name": "Eid Special", **body})
    assert response.status_code == 201, response.text
    return response.json()


async def _product_with(
    client: AsyncClient, headers: dict[str, str], badge_ids: list[str], **overrides: object
) -> dict:
    body = _product(**overrides)
    body.pop("badge")
    body["badge_ids"] = badge_ids
    response = await client.post(PRODUCTS, headers=headers, files=_parts(body))
    assert response.status_code == 201, response.text
    return response.json()


@contextmanager
def _selects(db: AsyncSession) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = db.bind.sync_engine  # type: ignore[union-attr]

    def count(_conn, _cursor, statement, *_rest) -> None:  # type: ignore[no-untyped-def]
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", count)


async def test_badges_are_admin_only(client: AsyncClient) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    assert (await client.post(ADMIN, json={"name": "X"})).status_code == 401


async def test_create_edit_and_list_badges(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _badge(client, auth_headers, name="  Eid   Special ", tone="soft-gold")
    assert created["name"] == "Eid Special"
    assert created["slug"] == "eid-special"
    assert created["tone"] == "soft-gold"
    assert created["is_active"] is True
    assert created["is_system"] is False
    assert created["product_count"] == 0

    duplicate = await client.post(ADMIN, headers=auth_headers, json={"name": "eid special"})
    assert duplicate.status_code == 409

    bad_tone = await client.post(ADMIN, headers=auth_headers, json={"name": "X", "tone": "#f00"})
    assert bad_tone.status_code == 422
    blank = await client.post(ADMIN, headers=auth_headers, json={"name": "   "})
    assert blank.status_code == 422
    too_long = await client.post(ADMIN, headers=auth_headers, json={"name": "x" * 33})
    assert too_long.status_code == 422
    extra = await client.post(ADMIN, headers=auth_headers, json={"name": "Y", "slug": "y"})
    assert extra.status_code == 422

    patched = await client.patch(
        f"{ADMIN}/{created['id']}",
        headers=auth_headers,
        json={"name": "Eid Offer", "tone": "alert", "is_active": False},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert (body["name"], body["tone"], body["is_active"]) == ("Eid Offer", "alert", False)
    assert body["slug"] == "eid-special"  # stable

    other = await _badge(client, auth_headers, name="Gift Pick")
    clash = await client.patch(
        f"{ADMIN}/{other['id']}", headers=auth_headers, json={"name": "EID OFFER"}
    )
    assert clash.status_code == 409

    listed = (await client.get(ADMIN, headers=auth_headers)).json()["items"]
    assert [item["name"] for item in listed] == ["Eid Offer", "Gift Pick"]
    assert (await client.get(f"{ADMIN}/{other['id']}", headers=auth_headers)).status_code == 200
    missing = await client.get(
        f"{ADMIN}/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert missing.status_code == 404


async def test_products_carry_badges_in_admin_and_public_views(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    system = await _seed_system(db_session)
    eid = await _badge(client, auth_headers, name="Eid Special", tone="soft")
    hidden = await _badge(client, auth_headers, name="Staff Pick", is_active=False)

    product = await _product_with(
        client,
        auth_headers,
        [eid["id"], system["best-seller"], hidden["id"], eid["id"]],
        slug="badged-gown",
    )
    assert [b["name"] for b in product["badges"]] == ["Eid Special", "Best Seller", "Staff Pick"]
    assert product["badges"][2]["is_active"] is False
    assert product["badge"] == "Best Seller"  # follows the built-in badge for ranking/filters

    admin_list = (await client.get(PRODUCTS, headers=auth_headers)).json()["items"]
    assert [b["slug"] for b in admin_list[0]["badges"]] == [
        "eid-special",
        "best-seller",
        "staff-pick",
    ]

    public = (await client.get("/api/v1/products")).json()["items"][0]
    assert public["badges"] == [
        {"name": "Eid Special", "slug": "eid-special", "tone": "soft"},
        {"name": "Best Seller", "slug": "best-seller", "tone": "gold"},
    ]
    assert "id" not in public["badges"][0]
    detail = (await client.get("/api/v1/products/by-slug/badged-gown")).json()
    assert [b["slug"] for b in detail["badges"]] == ["eid-special", "best-seller"]
    filtered = (await client.get("/api/v1/products", params={"badge": "Best Seller"})).json()
    assert filtered["total"] == 1

    # Switching a badge off hides it from shoppers without touching the product.
    await client.patch(f"{ADMIN}/{eid['id']}", headers=auth_headers, json={"is_active": False})
    public = (await client.get("/api/v1/products")).json()["items"][0]
    assert [b["slug"] for b in public["badges"]] == ["best-seller"]

    # Update: replace, reorder, then clear.
    patch = await client.patch(
        f"{PRODUCTS}/{product['id']}",
        headers=auth_headers,
        files=_parts({"badge_ids": [system["new"], eid["id"]]}),
    )
    assert patch.status_code == 200, patch.text
    assert [b["slug"] for b in patch.json()["badges"]] == ["new", "eid-special"]
    assert patch.json()["badge"] == "New"

    untouched = await client.patch(
        f"{PRODUCTS}/{product['id']}", headers=auth_headers, files=_parts({"price": 14000})
    )
    assert [b["slug"] for b in untouched.json()["badges"]] == ["new", "eid-special"]

    cleared = await client.patch(
        f"{PRODUCTS}/{product['id']}", headers=auth_headers, files=_parts({"badge_ids": []})
    )
    assert cleared.json()["badges"] == []
    assert cleared.json()["badge"] is None


async def test_unknown_or_too_many_badges_are_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = _product()
    body.pop("badge")
    body["badge_ids"] = ["00000000-0000-0000-0000-000000000001"]
    response = await client.post(PRODUCTS, headers=auth_headers, files=_parts(body))
    assert response.status_code == 422
    assert "badge" in response.text.lower()

    body["badge_ids"] = [f"00000000-0000-0000-0000-00000000000{i}" for i in range(9)]
    response = await client.post(PRODUCTS, headers=auth_headers, files=_parts(body))
    assert response.status_code == 422


async def test_legacy_badge_field_still_works(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    system = await _seed_system(db_session)
    custom = await _badge(client, auth_headers, name="Gift Pick")
    response = await client.post(PRODUCTS, headers=auth_headers, files=_parts(_product()))
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["badge"] == "New"
    assert [b["slug"] for b in created["badges"]] == ["new"]

    await client.patch(
        f"{PRODUCTS}/{created['id']}",
        headers=auth_headers,
        files=_parts({"badge_ids": [system["new"], custom["id"]]}),
    )
    # An old client that only knows `badge` swaps the built-in one and keeps custom badges.
    legacy = await client.patch(
        f"{PRODUCTS}/{created['id']}",
        headers=auth_headers,
        files=_parts({"badge": "Limited"}),
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["badge"] == "Limited"
    assert [b["slug"] for b in legacy.json()["badges"]] == ["limited", "gift-pick"]


async def test_delete_rules(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    system = await _seed_system(db_session)
    used = await _badge(client, auth_headers, name="Eid Special")
    unused = await _badge(client, auth_headers, name="Spare")
    product = await _product_with(client, auth_headers, [used["id"]])

    builtin = await client.delete(f"{ADMIN}/{system['new']}", headers=auth_headers)
    assert builtin.status_code == 409
    in_use = await client.delete(f"{ADMIN}/{used['id']}", headers=auth_headers)
    assert in_use.status_code == 409
    assert "1 product" in in_use.text

    gone = await client.delete(f"{ADMIN}/{unused['id']}", headers=auth_headers)
    assert gone.status_code == 200
    assert (await client.get(f"{ADMIN}/{unused['id']}", headers=auth_headers)).status_code == 404

    # Once the product is gone, its links go too and the badge can be deleted.
    assert (
        await client.delete(f"{PRODUCTS}/{product['id']}", headers=auth_headers)
    ).status_code in (
        200,
        204,
    )
    assert (await client.delete(f"{ADMIN}/{used['id']}", headers=auth_headers)).status_code == 200


async def test_lists_load_badges_in_one_query(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    badge = await _badge(client, auth_headers, name="Eid Special")
    for number in range(4):
        await _product_with(client, auth_headers, [badge["id"]], slug=f"gown-{number}")

    for url, headers in (
        ("/api/v1/products", {}),
        (PRODUCTS, auth_headers),
        ("/api/v1/products/by-slug/gown-0", {}),
    ):
        with _selects(db_session) as statements:
            response = await client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        badge_reads = [s for s in statements if "product_badges" in s]
        assert len(badge_reads) == 1, (url, badge_reads)

    search = (await client.get("/api/v1/search", params={"q": "gown"})).json()
    assert json.dumps(search).count("eid-special") >= 1
