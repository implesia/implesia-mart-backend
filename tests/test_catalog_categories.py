"""Hierarchical catalog: tree, validation, deletion, assignment, visibility, listing, stock."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import category_service
from tests.test_products import _create as create_product

ADMIN = "/api/v1/admin/categories"
PUBLIC = "/api/v1/categories"


def _form(body: dict) -> list:
    return [("payload", (None, json.dumps(body)))]


async def _cat(
    client: AsyncClient,
    headers: dict[str, str],
    name: str,
    parent_id: str | None = None,
    **extra: object,
) -> dict:
    body: dict = {"name": name, **extra}
    if parent_id is not None:
        body["parent_id"] = parent_id
    response = await client.post(ADMIN, headers=headers, files=_form(body))
    assert response.status_code == 201, response.text
    return response.json()


async def _patch(
    client: AsyncClient, headers: dict[str, str], category_id: str, body: dict
) -> tuple[int, dict]:
    response = await client.patch(f"{ADMIN}/{category_id}", headers=headers, files=_form(body))
    return response.status_code, response.json()


async def _tree(client: AsyncClient) -> list[dict]:
    response = await client.get(f"{PUBLIC}/tree")
    assert response.status_code == 200, response.text
    return response.json()["items"]


@pytest.fixture
async def demo(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, dict]:
    """Electronics > Home Appliances > (Bed Heaters, Electric Kettles); Food > Organic."""
    electronics = await _cat(client, auth_headers, "Electronics")
    appliances = await _cat(client, auth_headers, "Home Appliances", electronics["id"])
    heaters = await _cat(client, auth_headers, "Bed Heaters", appliances["id"])
    kettles = await _cat(client, auth_headers, "Electric Kettles", appliances["id"])
    food = await _cat(client, auth_headers, "Food and Grocery")
    organic = await _cat(client, auth_headers, "Organic Food", food["id"])
    return {
        "electronics": electronics,
        "appliances": appliances,
        "heaters": heaters,
        "kettles": kettles,
        "food": food,
        "organic": organic,
    }


# ----------------------------------------------------------------------------- tree


async def test_tree_is_nested_ordered_and_sent_with_an_etag(
    client: AsyncClient, demo: dict[str, dict]
) -> None:
    response = await client.get(f"{PUBLIC}/tree")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, no-cache"
    etag = response.headers["etag"]
    items = response.json()["items"]
    assert [node["name"] for node in items] == ["Electronics", "Food and Grocery"]
    electronics = items[0]
    assert electronics["depth"] == 1
    appliances = electronics["children"][0]
    assert appliances["slug"] == "home-appliances"
    assert [c["name"] for c in appliances["children"]] == ["Bed Heaters", "Electric Kettles"]
    assert appliances["children"][0]["depth"] == 3

    same = await client.get(f"{PUBLIC}/tree", headers={"If-None-Match": etag})
    assert same.status_code == 304
    assert same.content == b""


async def test_tree_etag_changes_when_the_tree_changes(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    before = (await client.get(f"{PUBLIC}/tree")).headers["etag"]
    await _cat(client, auth_headers, "Extra", demo["food"]["id"])
    after = await client.get(f"{PUBLIC}/tree", headers={"If-None-Match": before})
    assert after.status_code == 200
    assert after.headers["etag"] != before


async def test_tree_endpoint_uses_a_constant_number_of_queries(
    client: AsyncClient, db_session: AsyncSession, demo: dict[str, dict]
) -> None:
    from sqlalchemy import event

    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine  # type: ignore[union-attr]

    def count(_conn, _cursor, statement, *_rest) -> None:  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", count)
    try:
        response = await client.get(f"{PUBLIC}/tree")
    finally:
        event.remove(sync_engine, "before_cursor_execute", count)
    assert response.status_code == 200
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 2, selects  # categories + product counts, regardless of size


async def test_category_detail_has_breadcrumb_and_seo(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    status, _ = await _patch(
        client,
        auth_headers,
        demo["heaters"]["id"],
        {"meta_title": "Bed heaters", "meta_description": "Warm nights", "description": "Warm."},
    )
    assert status == 200
    detail = (await client.get(f"{PUBLIC}/bed-heaters")).json()
    assert [c["slug"] for c in detail["path"]] == ["electronics", "home-appliances", "bed-heaters"]
    assert detail["depth"] == 3
    assert detail["meta_title"] == "Bed heaters"
    assert (await client.get(f"{PUBLIC}/missing")).status_code == 404
    assert (await client.get(f"{PUBLIC}/Bad_Slug")).status_code == 422


# ----------------------------------------------------------------------------- validation


async def test_slug_is_generated_unique_and_conflicts_are_409(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    other = await _cat(client, auth_headers, "Kitchen")
    assert other["slug"] == "kitchen"
    explicit = await _cat(client, auth_headers, "Gadgets and More", slug="gizmos")
    assert explicit["slug"] == "gizmos"
    dup = await client.post(
        ADMIN, headers=auth_headers, files=_form({"name": "Another", "slug": "gizmos"})
    )
    assert dup.status_code == 409
    taken, _ = await _patch(client, auth_headers, other["id"], {"slug": "gizmos"})
    assert taken == 409
    for bad in ("Has Space", "tree", "order", "-x", "a--b"):
        response = await client.post(
            ADMIN, headers=auth_headers, files=_form({"name": "Bad", "slug": bad})
        )
        assert response.status_code == 422, bad
    # an auto slug never collides: same non-ascii name twice gets distinct slugs
    first = await _cat(client, auth_headers, "ফ্যাশন")
    second = await _cat(client, auth_headers, "ফ্যাশন", demo["food"]["id"])
    assert first["slug"] != second["slug"]


async def test_sibling_names_must_differ_but_other_parents_may_reuse_them(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    dup = await client.post(
        ADMIN,
        headers=auth_headers,
        files=_form({"name": "bed heaters", "parent_id": demo["appliances"]["id"]}),
    )
    assert dup.status_code == 409
    reused = await _cat(client, auth_headers, "Bed Heaters", demo["organic"]["id"])
    assert reused["slug"] != demo["heaters"]["slug"]


async def test_parent_must_exist_and_cannot_create_a_cycle(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    missing = await client.post(
        ADMIN, headers=auth_headers, files=_form({"name": "X", "parent_id": str(uuid.uuid4())})
    )
    assert missing.status_code == 422
    electronics = demo["electronics"]["id"]
    self_parent, _ = await _patch(client, auth_headers, electronics, {"parent_id": electronics})
    assert self_parent == 422
    under_child, body = await _patch(
        client, auth_headers, electronics, {"parent_id": demo["heaters"]["id"]}
    )
    assert under_child == 422
    assert "own subcategory" in body["error"]["message"]
    # nothing moved
    assert [n["name"] for n in await _tree(client)][0] == "Electronics"


async def test_depth_is_limited(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    from app.services.category_service import MAX_DEPTH

    parent: str | None = None
    for level in range(MAX_DEPTH):
        parent = (await _cat(client, auth_headers, f"Level {level}", parent))["id"]
    too_deep = await client.post(
        ADMIN, headers=auth_headers, files=_form({"name": "Too deep", "parent_id": parent})
    )
    assert too_deep.status_code == 422


async def test_move_between_parents_and_to_the_top_level(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    status, moved = await _patch(
        client, auth_headers, demo["appliances"]["id"], {"parent_id": demo["food"]["id"]}
    )
    assert status == 200 and moved["parent_id"] == demo["food"]["id"]
    assert [p["slug"] for p in moved["path"]] == ["food-and-grocery", "home-appliances"]
    status, top = await _patch(client, auth_headers, demo["appliances"]["id"], {"parent_id": None})
    assert status == 200 and top["parent_id"] is None
    status, kept = await _patch(client, auth_headers, demo["appliances"]["id"], {"name": "Appl"})
    assert status == 200 and kept["parent_id"] is None


async def test_reorder_within_a_parent(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    parent = demo["appliances"]["id"]
    ids = [demo["kettles"]["id"], demo["heaters"]["id"]]
    response = await client.put(
        ADMIN + "/order", headers=auth_headers, json={"parent_id": parent, "ids": ids}
    )
    assert response.status_code == 200, response.text
    appliances = (await _tree(client))[0]["children"][0]
    assert [c["name"] for c in appliances["children"]] == ["Electric Kettles", "Bed Heaters"]
    partial = await client.put(
        ADMIN + "/order", headers=auth_headers, json={"parent_id": parent, "ids": ids[:1]}
    )
    assert partial.status_code == 422
    wrong_level = await client.put(
        ADMIN + "/order", headers=auth_headers, json={"parent_id": None, "ids": ids}
    )
    assert wrong_level.status_code == 422


async def test_editor_role_is_required(client: AsyncClient, demo: dict[str, dict]) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    assert (await client.post(ADMIN, files=_form({"name": "No"}))).status_code == 401
    assert (await client.delete(f"{ADMIN}/{demo['food']['id']}")).status_code == 401


# ----------------------------------------------------------------------------- products


async def test_products_are_assigned_by_category_id_and_counted(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    heater = await create_product(
        client, auth_headers, title="Heater", category=None, category_id=demo["heaters"]["id"]
    )
    assert heater["category_id"] == demo["heaters"]["id"]
    assert heater["category_slug"] == "bed-heaters"
    assert [p["slug"] for p in heater["category_path"]] == [
        "electronics",
        "home-appliances",
        "bed-heaters",
    ]
    admin = (await client.get(ADMIN, headers=auth_headers)).json()
    rows = {row["slug"]: row for row in admin["items"]}
    assert rows["bed-heaters"]["product_count"] == 1
    assert rows["electronics"]["product_count"] == 0
    assert rows["electronics"]["subtree_product_count"] == 1
    assert rows["electronics"]["child_count"] == 1
    tree = await _tree(client)
    assert tree[0]["product_count"] == 1
    assert tree[1]["product_count"] == 0

    bad = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_form(_body(category=None, category_id=str(uuid.uuid4()))),
    )
    assert bad.status_code == 422


def _body(**overrides: object) -> dict:
    from tests.test_products import _product

    return _product(**overrides)


async def test_legacy_enum_filter_and_slug_keep_working(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await category_service.ensure_legacy(db_session, "gadgets")
    await category_service.ensure_legacy(db_session, "fashion")
    gadget = await create_product(client, auth_headers, title="Lamp", category="gadgets")
    await create_product(client, auth_headers, title="Gown", category="fashion")
    assert gadget["category"] == "gadgets"
    only = (await client.get("/api/v1/products", params={"category": "gadgets"})).json()
    assert [p["title"] for p in only["items"]] == ["Lamp"]
    assert only["items"][0]["category"] == "gadgets"
    counts = only["category_counts"]
    assert counts["gadgets"] == 1 and counts["fashion"] == 1
    unknown = await client.post(
        "/api/v1/admin/products", headers=auth_headers, files=_form(_body(category="nope"))
    )
    assert unknown.status_code == 422


async def test_listing_includes_descendants_by_default_and_can_be_narrowed(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    await create_product(
        client, auth_headers, title="H1", category=None, category_id=demo["heaters"]["id"]
    )
    await create_product(
        client, auth_headers, title="K1", category=None, category_id=demo["kettles"]["id"]
    )
    await create_product(
        client, auth_headers, title="O1", category=None, category_id=demo["organic"]["id"]
    )

    top = (await client.get(f"{PUBLIC}/electronics/products")).json()
    assert {p["title"] for p in top["items"]} == {"H1", "K1"}
    assert top["total"] == 2
    direct = (
        await client.get(f"{PUBLIC}/electronics/products", params={"include_descendants": "false"})
    ).json()
    assert direct["items"] == []
    leaf = (await client.get(f"{PUBLIC}/bed-heaters/products")).json()
    assert [p["title"] for p in leaf["items"]] == ["H1"]
    via_query = (
        await client.get("/api/v1/products", params={"category": "home-appliances"})
    ).json()
    assert via_query["total"] == 2
    unknown = (await client.get(f"{PUBLIC}/not-here/products")).json()
    assert unknown["items"] == [] and unknown["total"] == 0


async def test_listing_paginates_with_stable_totals(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    for number in range(5):
        await create_product(
            client,
            auth_headers,
            title=f"Heater {number}",
            category=None,
            category_id=demo["heaters"]["id"],
            price=1000 + number,
        )
    first = (
        await client.get(
            f"{PUBLIC}/bed-heaters/products", params={"page_size": 2, "sort": "price-asc"}
        )
    ).json()
    second = (
        await client.get(
            f"{PUBLIC}/bed-heaters/products",
            params={"page_size": 2, "page": 2, "sort": "price-asc"},
        )
    ).json()
    assert first["total"] == second["total"] == 5
    assert first["pages"] == 3
    assert [p["title"] for p in first["items"]] == ["Heater 0", "Heater 1"]
    assert [p["title"] for p in second["items"]] == ["Heater 2", "Heater 3"]
    assert (
        await client.get(f"{PUBLIC}/bed-heaters/products", params={"page_size": 49})
    ).status_code == 422
    assert (
        await client.get(f"{PUBLIC}/bed-heaters/products", params={"page": 0})
    ).status_code == 422


async def test_unpublished_products_stay_out_of_public_lists_and_counts(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    await create_product(
        client, auth_headers, title="Live", category=None, category_id=demo["kettles"]["id"]
    )
    await create_product(
        client,
        auth_headers,
        title="Draft",
        category=None,
        category_id=demo["kettles"]["id"],
        published=False,
    )
    listing = (await client.get(f"{PUBLIC}/electric-kettles/products")).json()
    assert [p["title"] for p in listing["items"]] == ["Live"]
    assert (await _tree(client))[0]["product_count"] == 1
    admin = {r["slug"]: r for r in (await client.get(ADMIN, headers=auth_headers)).json()["items"]}
    assert admin["electric-kettles"]["product_count"] == 2


# ----------------------------------------------------------------------------- visibility


async def test_inactive_category_hides_its_subtree_and_products(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    await create_product(
        client, auth_headers, title="H1", category=None, category_id=demo["heaters"]["id"]
    )
    status, body = await _patch(
        client, auth_headers, demo["appliances"]["id"], {"is_active": False}
    )
    assert status == 200 and body["visible"] is False
    tree = await _tree(client)
    electronics = tree[0]
    assert electronics["children"] == []  # appliances and everything below it is hidden
    assert (await client.get(f"{PUBLIC}/home-appliances")).status_code == 404
    assert (await client.get(f"{PUBLIC}/bed-heaters")).status_code == 404
    hidden_list = (await client.get(f"{PUBLIC}/bed-heaters/products")).json()
    assert hidden_list["items"] == []
    assert (await client.get(f"{PUBLIC}/electronics/products")).json()["items"] == []
    # the admin still sees and can reactivate everything
    admin = {r["slug"]: r for r in (await client.get(ADMIN, headers=auth_headers)).json()["items"]}
    assert admin["bed-heaters"]["visible"] is False
    assert admin["bed-heaters"]["is_active"] is True
    await _patch(client, auth_headers, demo["appliances"]["id"], {"is_active": True})
    assert len((await client.get(f"{PUBLIC}/electronics/products")).json()["items"]) == 1


# ----------------------------------------------------------------------------- deletion


async def test_delete_is_refused_while_children_or_products_exist(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    with_children = await client.delete(f"{ADMIN}/{demo['appliances']['id']}", headers=auth_headers)
    assert with_children.status_code == 409
    assert "2 subcategories" in with_children.json()["error"]["message"]
    await create_product(
        client, auth_headers, title="K", category=None, category_id=demo["kettles"]["id"]
    )
    with_products = await client.delete(f"{ADMIN}/{demo['kettles']['id']}", headers=auth_headers)
    assert with_products.status_code == 409
    assert "1 product" in with_products.json()["error"]["message"]
    empty = await client.delete(f"{ADMIN}/{demo['heaters']['id']}", headers=auth_headers)
    assert empty.status_code == 200
    assert (
        await client.get(f"{ADMIN}/{demo['heaters']['id']}", headers=auth_headers)
    ).status_code == 404


async def test_delete_with_reassignment_moves_products_and_children(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    product = await create_product(
        client, auth_headers, title="K", category=None, category_id=demo["appliances"]["id"]
    )
    removed = await client.delete(
        f"{ADMIN}/{demo['appliances']['id']}",
        headers=auth_headers,
        params={"reassign_to": demo["food"]["id"]},
    )
    assert removed.status_code == 200, removed.text
    moved = (
        await client.get(f"/api/v1/admin/products/{product['id']}", headers=auth_headers)
    ).json()
    assert moved["category_id"] == demo["food"]["id"]
    food = next(n for n in await _tree(client) if n["slug"] == "food-and-grocery")
    assert {c["slug"] for c in food["children"]} == {
        "organic-food",
        "bed-heaters",
        "electric-kettles",
    }


async def test_reassignment_target_is_validated(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    appliances = demo["appliances"]["id"]
    inside = await client.delete(
        f"{ADMIN}/{appliances}", headers=auth_headers, params={"reassign_to": demo["heaters"]["id"]}
    )
    assert inside.status_code == 422
    itself = await client.delete(
        f"{ADMIN}/{appliances}", headers=auth_headers, params={"reassign_to": appliances}
    )
    assert itself.status_code == 422
    nowhere = await client.delete(
        f"{ADMIN}/{appliances}", headers=auth_headers, params={"reassign_to": str(uuid.uuid4())}
    )
    assert nowhere.status_code == 422
    assert (await client.get(f"{ADMIN}/{appliances}", headers=auth_headers)).status_code == 200


# ----------------------------------------------------------------------------- stock


async def test_public_catalog_never_exposes_the_inventory_count(
    client: AsyncClient, auth_headers: dict[str, str], demo: dict[str, dict]
) -> None:
    product = await create_product(
        client,
        auth_headers,
        title="Counted",
        category=None,
        category_id=demo["kettles"]["id"],
        quantity=3,
    )
    listing = (await client.get(f"{PUBLIC}/electric-kettles/products")).json()
    card = listing["items"][0]
    detail = (await client.get(f"/api/v1/products/by-slug/{product['slug']}")).json()
    for body in (card, detail):
        assert "quantity" not in body
        assert "quantity" not in json.dumps(body)
        assert body["status"] == "available"
    assert "unit_label" in card


async def test_cart_refuses_more_than_can_be_bought_without_naming_the_stock(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await create_product(client, auth_headers, title="Scarce", quantity=2)
    first = await client.post(
        "/api/v1/cart/items", json={"product_id": product["id"], "quantity": 2}
    )
    assert first.status_code == 200
    token = first.json()["cart_token"]
    more = await client.post(
        "/api/v1/cart/items",
        headers={"X-Cart-Token": token},
        json={"product_id": product["id"], "quantity": 1},
    )
    assert more.status_code == 422
    assert not any(ch.isdigit() for ch in more.json()["error"]["message"])
    item_id = first.json()["items"][0]["id"]
    raise_it = await client.patch(
        f"/api/v1/cart/items/{item_id}", headers={"X-Cart-Token": token}, json={"quantity": 3}
    )
    assert raise_it.status_code == 422
    over_cap = await client.post(
        "/api/v1/cart/items", json={"product_id": product["id"], "quantity": 6}
    )
    assert over_cap.status_code == 422
