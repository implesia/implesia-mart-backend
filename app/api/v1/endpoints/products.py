import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import DbSession, no_store
from app.schemas.product import CatalogQuery, PublicProductDetail, PublicProductList
from app.services import product_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("", response_model=PublicProductList)
async def list_products(
    db: DbSession,
    query: Annotated[CatalogQuery, Depends()],
) -> PublicProductList:
    return await product_service.list_public(db, query)


@router.get("/by-slug/{slug}", response_model=PublicProductDetail)
async def read_product_by_slug(
    db: DbSession,
    slug: Annotated[str, Path(min_length=1, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")],
) -> PublicProductDetail:
    return await product_service.read_public_by_slug(db, slug)


@router.get("/{product_id}", response_model=PublicProductDetail)
async def read_product(db: DbSession, product_id: uuid.UUID) -> PublicProductDetail:
    return await product_service.read_public(db, product_id)
