import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

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


@router.get("/{product_id}", response_model=PublicProductDetail)
async def read_product(db: DbSession, product_id: uuid.UUID) -> PublicProductDetail:
    return await product_service.read_public(db, product_id)
