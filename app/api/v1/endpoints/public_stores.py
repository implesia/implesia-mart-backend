"""Public multi-tenant dropshipper storefront & checkout endpoints (/api/v1/public/stores/*)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request, status

from app.api.deps import DbSession
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.dropshipper_store import (
    PublicStorefrontRead,
    PublicStoreOrderCreateRequest,
    PublicStoreOrderCreateResponse,
    PublicStoreOrderQuoteRequest,
    PublicStoreOrderQuoteResponse,
    PublicStoreProductListResponse,
    PublicStoreProductRead,
)
from app.services import dropshipper_store_service, meta_capi

router = APIRouter()


@router.get("/{slug}", response_model=PublicStorefrontRead)
async def get_public_store(
    slug: str,
    db: DbSession,
) -> PublicStorefrontRead:
    return await dropshipper_store_service.public_get_store(db, slug)


@router.get("/{slug}/products", response_model=PublicStoreProductListResponse)
async def list_public_store_products(
    slug: str,
    db: DbSession,
    q: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=80),
    featured: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=60),
) -> PublicStoreProductListResponse:
    return await dropshipper_store_service.public_list_products(
        db,
        slug,
        q=q,
        category=category,
        featured=featured,
        page=page,
        page_size=page_size,
    )


@router.get("/{slug}/products/{product_slug}", response_model=PublicStoreProductRead)
async def get_public_store_product(
    slug: str,
    product_slug: str,
    db: DbSession,
) -> PublicStoreProductRead:
    return await dropshipper_store_service.public_get_product(db, slug, product_slug)


@router.post("/{slug}/orders/quote", response_model=PublicStoreOrderQuoteResponse)
async def quote_public_store_order(
    slug: str,
    payload: PublicStoreOrderQuoteRequest,
    db: DbSession,
) -> PublicStoreOrderQuoteResponse:
    return await dropshipper_store_service.public_quote_order(db, slug, payload)


@router.post(
    "/{slug}/orders",
    response_model=PublicStoreOrderCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.rate_limit_orders)
async def create_public_store_order(
    slug: str,
    request: Request,
    payload: PublicStoreOrderCreateRequest,
    db: DbSession,
    background: BackgroundTasks,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> PublicStoreOrderCreateResponse:
    client_ip = meta_capi.client_ip_address(request)
    user_agent = request.headers.get("user-agent")
    return await dropshipper_store_service.public_create_order(
        db,
        slug,
        payload,
        idempotency_key=idempotency_key,
        background=background,
        client_ip=client_ip,
        user_agent=user_agent,
    )
