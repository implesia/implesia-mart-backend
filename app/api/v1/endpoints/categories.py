import hashlib
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError, payload_errors
from app.rate_limit import limiter
from app.schemas.category import (
    CategoryAdminList,
    CategoryAdminRead,
    CategoryDetail,
    CategoryOrder,
    CategoryTree,
    CategoryUpdate,
    CategoryWrite,
)
from app.schemas.common import Message
from app.schemas.product import CatalogQuery, PublicProductList
from app.services import category_service, product_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 20_000
_SLUG_PATH = Path(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _payload(
    raw: str, model: type[CategoryWrite] | type[CategoryUpdate]
) -> CategoryWrite | CategoryUpdate:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Category details are too large")
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid", payload_errors(exc)) from exc


# ------------------------------------------------------------------ public


@public_router.get("/tree", response_model=CategoryTree)
async def read_tree(
    db: DbSession,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response | CategoryTree:
    """The whole visible tree in one query. Revalidated on every request with an ETag, so a
    change in the dashboard shows up immediately and an unchanged tree costs a 304."""
    tree = await category_service.public_tree(db)
    body = tree.model_dump_json()
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": "public, no-cache"}
    if if_none_match is not None and etag in {part.strip() for part in if_none_match.split(",")}:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@public_router.get("/{slug}", response_model=CategoryDetail, dependencies=[Depends(no_store)])
async def read_category(db: DbSession, slug: Annotated[str, _SLUG_PATH]) -> CategoryDetail:
    return await category_service.public_detail(db, slug)


@public_router.get(
    "/{slug}/products", response_model=PublicProductList, dependencies=[Depends(no_store)]
)
async def read_category_products(
    db: DbSession,
    slug: Annotated[str, _SLUG_PATH],
    query: Annotated[CatalogQuery, Depends()],
) -> PublicProductList:
    """Products of one category (its subcategories included unless
    `include_descendants=false`). Same filters, sorting, and pagination as /products."""
    scoped = query.model_copy(update={"category": slug, "category_id": None})
    return await product_service.list_public(db, scoped)


# ------------------------------------------------------------------ admin


@admin_router.get("", response_model=CategoryAdminList)
async def list_categories(db: DbSession) -> CategoryAdminList:
    return await category_service.admin_list(db)


@admin_router.post("", response_model=CategoryAdminRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_category(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    image: Annotated[UploadFile | None, File()] = None,
) -> CategoryAdminRead:
    del request
    data = _payload(payload, CategoryWrite)
    assert isinstance(data, CategoryWrite)
    row = await category_service.create(db, data, image)
    return await category_service.admin_read(db, row.id)


@admin_router.put("/order", response_model=CategoryAdminList)
@limiter.limit(settings.rate_limit_product_writes)
async def reorder_categories(
    request: Request, db: DbSession, payload: CategoryOrder
) -> CategoryAdminList:
    del request
    await category_service.reorder(db, payload)
    return await category_service.admin_list(db)


@admin_router.get("/{category_id}", response_model=CategoryAdminRead)
async def read_admin_category(db: DbSession, category_id: uuid.UUID) -> CategoryAdminRead:
    return await category_service.admin_read(db, category_id)


@admin_router.patch("/{category_id}", response_model=CategoryAdminRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_category(
    request: Request,
    db: DbSession,
    category_id: uuid.UUID,
    payload: Annotated[str, Form()] = "{}",
    image: Annotated[UploadFile | None, File()] = None,
) -> CategoryAdminRead:
    del request
    data = _payload(payload, CategoryUpdate)
    assert isinstance(data, CategoryUpdate)
    row = await category_service.get(db, category_id)
    await category_service.update_category(db, row, data, image)
    return await category_service.admin_read(db, category_id)


@admin_router.delete("/{category_id}", response_model=Message)
@limiter.limit(settings.rate_limit_product_writes)
async def delete_category(
    request: Request,
    db: DbSession,
    category_id: uuid.UUID,
    reassign_to: Annotated[uuid.UUID | None, Query()] = None,
) -> Message:
    del request
    row = await category_service.get(db, category_id)
    await category_service.delete_category(db, row, reassign_to=reassign_to)
    return Message(message="Category deleted")
