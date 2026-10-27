import json
import uuid

from httpx import AsyncClient

BASE = "/api/v1/admin/home/categories/tiles"


async def _create(
    client: AsyncClient, headers: dict[str, str], label: str, parent_id: str | None = None
) -> dict:
    body: dict[str, object] = {"label": label, "href": f"/products?category={label.lower()}"}
    if parent_id is not None:
        body["parent_id"] = parent_id
    response = await client.post(
        BASE, headers=headers, files=[("payload", (None, json.dumps(body)))]
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _patch(
    client: AsyncClient, headers: dict[str, str], tile_id: str, body: dict
) -> tuple[int, dict]:
    response = await client.patch(
        f"{BASE}/{tile_id}", headers=headers, files=[("payload", (None, json.dumps(body)))]
    )
    return response.status_code, response.json()


async def test_nested_categories_round_trip_to_admin_and_public(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    root = await _create(client, auth_headers, "Electronics")
    child = await _create(client, auth_headers, "Phones", root["id"])
    grandchild = await _create(client, auth_headers, "Android", child["id"])
    assert root["parent_id"] is None
    assert child["parent_id"] == root["id"]
    assert grandchild["parent_id"] == child["id"]

    public = (await client.get("/api/v1/home/categories")).json()["tiles"]
    parents = {tile["id"]: tile["parent_id"] for tile in public}
    assert parents[grandchild["id"]] == child["id"]
    assert parents[child["id"]] == root["id"]

    admin = (await client.get("/api/v1/admin/home/categories", headers=auth_headers)).json()
    assert {tile["id"]: tile["parent_id"] for tile in admin["tiles"]}[child["id"]] == root["id"]


async def test_parent_validation_rejects_self_descendants_and_missing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    root = await _create(client, auth_headers, "Home")
    child = await _create(client, auth_headers, "Kitchen", root["id"])
    grandchild = await _create(client, auth_headers, "Kettles", child["id"])

    status, body = await _patch(client, auth_headers, root["id"], {"parent_id": root["id"]})
    assert status == 422, body
    status, body = await _patch(client, auth_headers, root["id"], {"parent_id": grandchild["id"]})
    assert status == 422, body
    assert "subcategory" in body["error"]["message"]
    status, body = await _patch(client, auth_headers, child["id"], {"parent_id": str(uuid.uuid4())})
    assert status == 422, body

    missing = await client.post(
        BASE,
        headers=auth_headers,
        files=[("payload", (None, json.dumps({"label": "x", "parent_id": str(uuid.uuid4())})))],
    )
    assert missing.status_code == 422, missing.text


async def test_parent_can_move_and_return_to_top_level(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await _create(client, auth_headers, "First")
    second = await _create(client, auth_headers, "Second")
    status, body = await _patch(client, auth_headers, second["id"], {"parent_id": first["id"]})
    assert status == 200, body
    assert body["parent_id"] == first["id"]
    # Omitting parent_id keeps it.
    status, body = await _patch(client, auth_headers, second["id"], {"label": "Second+"})
    assert body["parent_id"] == first["id"]
    status, body = await _patch(client, auth_headers, second["id"], {"parent_id": None})
    assert status == 200, body
    assert body["parent_id"] is None


async def test_hidden_parent_hides_its_subtree_on_the_storefront(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    root = await _create(client, auth_headers, "Toys")
    child = await _create(client, auth_headers, "Blocks", root["id"])
    await _patch(client, auth_headers, root["id"], {"is_active": False})
    public_ids = {t["id"] for t in (await client.get("/api/v1/home/categories")).json()["tiles"]}
    assert root["id"] not in public_ids
    assert child["id"] not in public_ids


async def test_deleting_a_parent_moves_children_up_one_level(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    root = await _create(client, auth_headers, "Garden")
    middle = await _create(client, auth_headers, "Tools", root["id"])
    leaf = await _create(client, auth_headers, "Shovels", middle["id"])
    deleted = await client.delete(f"{BASE}/{middle['id']}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    admin = (await client.get("/api/v1/admin/home/categories", headers=auth_headers)).json()
    assert {t["id"]: t["parent_id"] for t in admin["tiles"]}[leaf["id"]] == root["id"]


def test_index_hides_inactive_subtrees_and_survives_orphans_and_cycles() -> None:
    from app.models.category import Category
    from app.services.category_service import CategoryIndex

    def node(parent: uuid.UUID | None, active: bool = True) -> Category:
        ident = uuid.uuid4()
        return Category(
            id=ident, parent_id=parent, is_active=active, name="t", slug=f"t-{ident.hex[:8]}"
        )

    orphan = node(uuid.uuid4())
    a = node(None)
    b = node(a.id)
    a.parent_id = b.id  # corrupt cycle a <-> b must not hang
    hidden = node(None, active=False)
    under_hidden = node(hidden.id)
    index = CategoryIndex([orphan, a, b, hidden, under_hidden])
    assert index.hidden_ids() >= {hidden.id, under_hidden.id}
    assert orphan.id not in index.hidden_ids()
    assert len(index.path(a.id)) <= 12
