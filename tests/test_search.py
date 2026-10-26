"""Phase 4: global search (products and blogs) and the `q` filter on the public catalog."""

import pytest
from httpx import AsyncClient

from app.models.product import ProductBadge  # noqa: F401  (keeps model import order stable)
from app.schemas.product import PublicProductCard
from app.schemas.search import BlogHit
from app.services import search_text
from tests.test_blog_posts import _category_id, _post
from tests.test_catalog_categories import _cat, _patch
from tests.test_products import _create

SEARCH = "/api/v1/search"
ERROR_KEYS = {"code", "message", "details"}


async def _get(client: AsyncClient, **params: str | int) -> dict:
    response = await client.get(SEARCH, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _titles(group: dict) -> list[str]:
    return [item["title"] for item in group["items"]]


async def _blog(
    client: AsyncClient, headers: dict[str, str], category_id: str, **overrides: object
) -> dict:
    body = {**_post(category_id=category_id), **overrides}
    response = await client.post("/api/v1/admin/pages/blogs/posts", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- normalisation


def test_normalize_collapses_space_and_strips_control_characters() -> None:
    assert search_text.normalize_query("  Red \t\n  Shirt\x00 ") == "Red Shirt"
    assert search_text.normalize_query(None) == ""
    assert search_text.normalize_query("   ") == ""
    assert len(search_text.normalize_query("a" * 500)) == search_text.MAX_QUERY_CHARS


def test_normalize_composes_unicode_but_keeps_bangla_joiners() -> None:
    assert search_text.normalize_query("e\u0301") == "\u00e9"
    assert search_text.normalize_query("র\u200d্যাব") == "র\u200d্যাব"
    assert search_text.normalize_query("a\u200bb") == "a b"


def test_tokenize_lowercases_trims_edges_dedupes_and_caps() -> None:
    assert search_text.tokenize('  "Red", (shirt)!  RED ') == ["red", "shirt"]
    assert search_text.tokenize("লাল শার্ট") == ["লাল", "শার্ট"]
    assert search_text.tokenize("?! ... --") == []
    assert len(search_text.tokenize("a b c d e f g h")) == search_text.MAX_TOKENS


# ---------------------------------------------------------------------------------- products


async def test_products_match_words_in_any_order_and_any_case(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="Red Cotton Shirt", subtitle="Summer wear")
    await _create(client, auth_headers, title="Blue Denim Jeans", subtitle="Winter wear")
    for term in ("red shirt", "SHIRT RED", "  cotton   red ", "sh", "Red,"):
        assert _titles((await _get(client, q=term))["products"]) == ["Red Cotton Shirt"], term
    both = await _get(client, q="wear")
    assert sorted(_titles(both["products"])) == ["Blue Denim Jeans", "Red Cotton Shirt"]
    assert (await _get(client, q="red jeans"))["products"]["total"] == 0


async def test_bangla_terms_match_bangla_titles_and_partial_words(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="লাল সুতি শার্ট", subtitle="গরমের জন্য")
    await _create(client, auth_headers, title="নীল জিন্স", subtitle="শীতের জন্য")
    assert _titles((await _get(client, q="লাল শার্ট"))["products"]) == ["লাল সুতি শার্ট"]
    assert _titles((await _get(client, q="শার্ট"))["products"]) == ["লাল সুতি শার্ট"]
    assert _titles((await _get(client, q="জিন্স"))["products"]) == ["নীল জিন্স"]
    assert (await _get(client, q="জন্য"))["products"]["total"] == 2
    assert (await _get(client, q="নেই"))["products"]["total"] == 0


async def test_products_match_their_category_name_and_slug(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    kettles = await _cat(client, auth_headers, "Electric Kettles")
    await _create(client, auth_headers, title="Steel jug", category=None, category_id=kettles["id"])
    await _create(client, auth_headers, title="Plain mug", slug="special-mug-edition")
    assert _titles((await _get(client, q="kettles"))["products"]) == ["Steel jug"]
    assert _titles((await _get(client, q="special edition"))["products"]) == ["Plain mug"]


async def test_title_hits_rank_above_subtitle_hits(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="Garden hose", subtitle="Great lamp stand")
    await _create(client, auth_headers, title="Desk lamp", subtitle="Warm light")
    ranked = _titles((await _get(client, q="lamp"))["products"])
    assert ranked == ["Desk lamp", "Garden hose"]


async def test_unpublished_products_and_hidden_categories_never_appear(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="Secret draft lamp", published=False)
    hidden = await _cat(client, auth_headers, "Hidden Lamps")
    await _create(
        client, auth_headers, title="Hidden shelf lamp", category=None, category_id=hidden["id"]
    )
    await _create(client, auth_headers, title="Visible lamp")
    await _patch(client, auth_headers, hidden["id"], {"is_active": False})
    found = await _get(client, q="lamp")
    assert _titles(found["products"]) == ["Visible lamp"]
    assert found["products"]["total"] == 1


async def test_product_items_expose_only_the_public_card(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="Card lamp", quantity=3)
    item = (await _get(client, q="card"))["products"]["items"][0]
    assert set(item) == set(PublicProductCard.model_fields)
    assert {"quantity", "published", "content", "has_stock"}.isdisjoint(item)


async def test_wildcards_and_injection_text_are_literal(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="Plain lamp")
    await _create(client, auth_headers, title="Fifty% off lamp")
    # Unescaped, `plain%lamp` and `pl_in` would both match "Plain lamp".
    for term in ("%", "_", "%%", "plain%lamp", "pl_in", r"pl\\ain", "x_y"):
        assert (await _get(client, q=term))["products"]["total"] == 0, term
    assert (await _get(client, q="fifty%"))["products"]["total"] == 1
    for term in ("' OR '1'='1", "'; DROP TABLE products; --", '" OR 1=1 --', "lamp') OR ('1'='1"):
        assert (await _get(client, q=term))["products"]["total"] == 0, term
    assert (await _get(client, q="plain"))["products"]["total"] == 1


async def test_pagination_walks_every_match_once(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for number in range(5):
        await _create(client, auth_headers, title=f"Bulk lamp {number}", featured=False)
    seen: list[str] = []
    for page in (1, 2, 3):
        group = (await _get(client, q="bulk", type="products", page=page, page_size=2))["products"]
        assert group["total"] == 5 and group["pages"] == 3 and group["page"] == page
        seen += _titles(group)
    assert len(seen) == 5 and len(set(seen)) == 5
    beyond = (await _get(client, q="bulk", type="products", page=9, page_size=2))["products"]
    assert beyond["items"] == [] and beyond["total"] == 5


async def test_type_limits_which_groups_are_searched(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category = await _category_id(client, auth_headers)
    await _create(client, auth_headers, title="Guide lamp")
    await _blog(client, auth_headers, category, title="Lamp guide", slug="lamp-guide")
    both = await _get(client, q="lamp")
    assert both["products"]["total"] == 1 and both["blogs"]["total"] == 1
    only_products = await _get(client, q="lamp", type="products")
    assert only_products["products"]["total"] == 1 and only_products["blogs"]["total"] == 0
    only_blogs = await _get(client, q="lamp", type="blogs")
    assert only_blogs["products"]["total"] == 0 and only_blogs["blogs"]["total"] == 1


# ------------------------------------------------------------------------------------ blogs


async def test_blogs_match_title_excerpt_tag_author_and_active_body(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category = await _category_id(client, auth_headers)
    await _blog(
        client,
        auth_headers,
        category,
        title="Battery care",
        slug="battery-care",
        excerpt="Make a charger last",
        author="Nusrat",
        tags=["charging"],
    )
    for term, expect in (
        ("battery", 1),
        ("charger", 1),
        ("charging", 1),
        ("nusrat", 1),
        ("start here", 1),
        ("care charger", 1),
        ("battery nothing", 0),
    ):
        assert (await _get(client, q=term, type="blogs"))["blogs"]["total"] == expect, term


async def test_blogs_never_show_inactive_posts_or_inactive_blocks(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category = await _category_id(client, auth_headers)
    await _blog(client, auth_headers, category, slug="live-one", title="Live guide")
    await _blog(
        client, auth_headers, category, slug="draft-one", title="Draft guide", is_active=False
    )
    found = await _get(client, q="guide", type="blogs")
    assert _titles(found["blogs"]) == ["Live guide"]
    # The post's second block ("Hidden") is inactive, so it is not searchable.
    assert (await _get(client, q="hidden", type="blogs"))["blogs"]["total"] == 0


async def test_blog_items_expose_only_the_public_hit(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category = await _category_id(client, auth_headers)
    await _blog(client, auth_headers, category, slug="shape-one", title="Shape guide")
    item = (await _get(client, q="shape", type="blogs"))["blogs"]["items"][0]
    assert set(item) == set(BlogHit.model_fields)
    assert {"is_active", "blocks", "related_product_slugs", "category_id"}.isdisjoint(item)


# -------------------------------------------------------------------------------- contract


async def test_blank_and_symbol_only_queries_answer_empty_success(client: AsyncClient) -> None:
    for params in ({}, {"q": ""}, {"q": "   "}, {"q": "?!"}):
        body = await _get(client, **params)
        assert body["products"] == {"items": [], "total": 0, "page": 1, "pages": 0}
        assert body["blogs"] == {"items": [], "total": 0, "page": 1, "pages": 0}


async def test_response_reports_the_normalised_query(client: AsyncClient) -> None:
    body = await _get(client, q="  Red   SHIRT ")
    assert body["query"] == "red shirt"
    assert body["type"] == "all" and body["page_size"] == 8


@pytest.mark.parametrize(
    "params",
    [
        {"q": "x" * 101},
        {"q": "ok", "type": "orders"},
        {"q": "ok", "page": 0},
        {"q": "ok", "page": "abc"},
        {"q": "ok", "page_size": 25},
        {"q": "ok", "page_size": 0},
    ],
)
async def test_invalid_parameters_use_the_error_envelope(
    client: AsyncClient, params: dict[str, str | int]
) -> None:
    response = await client.get(SEARCH, params=params)
    assert response.status_code == 422
    assert set(response.json()["error"]) >= {"code", "message"}


async def test_search_is_public_and_never_cached(client: AsyncClient) -> None:
    response = await client.get(SEARCH, params={"q": "lamp"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


# ------------------------------------------------------------- catalog filter (`/products?q=`)


async def test_catalog_q_filters_with_counts_and_other_filters(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Distinct subtitles: the default one ("...embroidered...") contains "red" as a substring.
    await _create(client, auth_headers, title="Red lamp", subtitle="x", category="gadgets")
    await _create(client, auth_headers, title="Red gown", subtitle="x", category="fashion")
    await _create(client, auth_headers, title="Blue gown", subtitle="x", category="fashion")
    listed = (await client.get("/api/v1/products", params={"q": "red"})).json()
    assert sorted(_titles(listed)) == ["Red gown", "Red lamp"]
    assert listed["total"] == 2
    assert listed["category_counts"] == {"gadgets": 1, "fashion": 1}
    narrowed = (
        await client.get("/api/v1/products", params={"q": "red", "category": "gadgets"})
    ).json()
    assert _titles(narrowed) == ["Red lamp"]
    assert (await client.get("/api/v1/products", params={"q": ""})).json()["total"] == 3
    assert (await client.get("/api/v1/products", params={"q": "x" * 101})).status_code == 422


async def test_catalog_q_is_found_beyond_the_first_pages(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """The old storefront scanned four pages of 48; search must reach any product."""
    for number in range(3):
        await _create(client, auth_headers, title=f"Filler {number}")
    await _create(client, auth_headers, title="Needle item", featured=False)
    listed = (
        await client.get("/api/v1/products", params={"q": "needle", "page_size": 1, "page": 1})
    ).json()
    assert _titles(listed) == ["Needle item"]
