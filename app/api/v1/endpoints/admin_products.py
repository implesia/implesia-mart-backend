import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import ValidationError

from app.api.deps import DbSession, RequireEditor, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.product import (
    AdminProductList,
    AdminProductQuery,
    AdminProductRead,
    ProductCreate,
    ProductUpdate,
)
from app.services import product_service

router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 200_000


def _model(
    raw: str, model: type[ProductCreate] | type[ProductUpdate]
) -> ProductCreate | ProductUpdate:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Product details are too large")
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


def _alts(raw: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnprocessableError("image_alts must be a JSON list") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise UnprocessableError("image_alts must be a JSON list of strings")
    if len(parsed) > 12:
        raise UnprocessableError("A product can have at most 12 images")
    return parsed


@router.get("", response_model=AdminProductList)
async def list_products(
    db: DbSession,
    query: Annotated[AdminProductQuery, Depends()],
) -> AdminProductList:
    return await product_service.list_admin(db, query)


@router.post("", response_model=AdminProductRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_product(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    images: Annotated[list[UploadFile] | None, File()] = None,
    image_alts: Annotated[str, Form()] = "[]",
    quality_image: Annotated[UploadFile | None, File()] = None,
    quality_image_alt: Annotated[str, Form()] = "",
) -> AdminProductRead:
    del request
    data = _model(payload, ProductCreate)
    assert isinstance(data, ProductCreate)
    product = await product_service.create_product(
        db,
        data,
        images,
        _alts(image_alts),
        quality_image,
        quality_image_alt,
    )
    return product_service.admin_read(product)


@router.get("/{product_id}", response_model=AdminProductRead)
async def read_product(db: DbSession, product_id: uuid.UUID) -> AdminProductRead:
    product = await product_service.get_by_id(db, product_id)
    return product_service.admin_read(product)


@router.patch("/{product_id}", response_model=AdminProductRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_product(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    product_id: uuid.UUID,
    payload: Annotated[str, Form()] = "{}",
    images: Annotated[list[UploadFile] | None, File()] = None,
    image_alts: Annotated[str, Form()] = "[]",
    quality_image: Annotated[UploadFile | None, File()] = None,
    quality_image_alt: Annotated[str, Form()] = "",
) -> AdminProductRead:
    del request
    data = _model(payload, ProductUpdate)
    assert isinstance(data, ProductUpdate)
    product = await product_service.get_by_id(db, product_id)
    updated = await product_service.update_product(
        db,
        product,
        data,
        images,
        _alts(image_alts),
        quality_image,
        quality_image_alt,
        actor=actor,
    )
    return product_service.admin_read(updated)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(db: DbSession, product_id: uuid.UUID) -> None:
    product = await product_service.get_by_id(db, product_id)
    await product_service.delete_product(db, product)
