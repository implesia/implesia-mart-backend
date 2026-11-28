"""Multi-tenant dropshipper storefront builder & public storefront/checkout service."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.models.category import Category
from app.models.dropshipper_store import (
    DropshipperStore,
    DropshipperStoreProduct,
    StoreTemplateId,
)
from app.models.dropshipping import DropshipperProfile, DropshipperStatus
from app.models.order import Order
from app.models.product import Product, ProductVariant, StockStatus
from app.models.user import User
from app.schemas.common import page_count
from app.schemas.dropshipper_store import (
    RESERVED_STORE_SLUGS,
    DropshipperStoreProductImportRequest,
    DropshipperStoreProductListResponse,
    DropshipperStoreProductRead,
    DropshipperStoreProductUpdate,
    DropshipperStoreRead,
    DropshipperStoreSeoTrackingUpdate,
    DropshipperStoreUpdate,
    PublicStorefrontRead,
    PublicStoreMediaItem,
    PublicStoreOrderCreateRequest,
    PublicStoreOrderCreateResponse,
    PublicStoreOrderQuoteLine,
    PublicStoreOrderQuoteRequest,
    PublicStoreOrderQuoteResponse,
    PublicStoreProductListResponse,
    PublicStoreProductRead,
    PublicStoreVariantRead,
    StoreBrandConfig,
    StoreHeroConfig,
    StoreSectionConfig,
    StoreThemeConfig,
)
from app.schemas.dropshipping import (
    DropshipOrderCreateRequest,
    DropshipOrderItemInput,
    DropshipOrderQuoteRequest,
)
from app.schemas.order import purchase_event_id
from app.services import dropship_order_service, meta_capi


def _default_sections() -> list[dict[str, Any]]:
    return [
        {
            "id": "hero",
            "type": "hero",
            "enabled": True,
            "title": "",
            "subtitle": "",
            "order": 0,
        },
        {
            "id": "trust_badges",
            "type": "trust_badges",
            "enabled": True,
            "title": "Why Shop With Us",
            "subtitle": "",
            "order": 1,
        },
        {
            "id": "featured_products",
            "type": "featured_products",
            "enabled": True,
            "title": "Featured Collection",
            "subtitle": "Hand-picked bestsellers",
            "order": 2,
        },
        {
            "id": "categories",
            "type": "categories",
            "enabled": True,
            "title": "Shop by Category",
            "subtitle": "",
            "order": 3,
        },
        {
            "id": "all_products",
            "type": "all_products",
            "enabled": True,
            "title": "All Products",
            "subtitle": "",
            "order": 4,
        },
        {
            "id": "promo_banner",
            "type": "promo_banner",
            "enabled": False,
            "title": "Limited Time Offer",
            "subtitle": "Cash on Delivery across Bangladesh",
            "order": 5,
        },
        {
            "id": "reviews",
            "type": "reviews",
            "enabled": True,
            "title": "Happy Customers",
            "subtitle": "",
            "order": 6,
        },
    ]


def _safe_slug(raw: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in raw.lower()).strip("-")
    if len(cleaned) < 3 or cleaned in RESERVED_STORE_SLUGS:
        return f"shop-{uuid.uuid4().hex[:6]}"
    return cleaned[:76]


async def _unique_store_slug(
    db: AsyncSession,
    desired: str,
    *,
    exclude_store_id: uuid.UUID | None = None,
) -> str:
    base = _safe_slug(desired)
    candidate = base
    suffix = 2
    while True:
        stmt = select(DropshipperStore.id).where(DropshipperStore.slug == candidate)
        if exclude_store_id is not None:
            stmt = stmt.where(DropshipperStore.id != exclude_store_id)
        existing = await db.scalar(stmt)
        if existing is None and candidate not in RESERVED_STORE_SLUGS:
            return candidate
        candidate = f"{base[:70]}-{suffix}"
        suffix += 1


def _store_to_read(store: DropshipperStore) -> DropshipperStoreRead:
    return DropshipperStoreRead(
        id=store.id,
        dropshipper_id=store.dropshipper_id,
        profile_id=store.profile_id,
        slug=store.slug,
        is_published=store.is_published,
        template_id=StoreTemplateId(store.template_id),
        theme_config=StoreThemeConfig.model_validate(store.theme_config or {}),
        brand_config=StoreBrandConfig.model_validate(store.brand_config or {}),
        hero_config=StoreHeroConfig.model_validate(store.hero_config or {}),
        sections_config=[
            StoreSectionConfig.model_validate(s) for s in (store.sections_config or [])
        ],
        seo_title=store.seo_title,
        seo_description=store.seo_description,
        seo_og_image_url=store.seo_og_image_url,
        google_site_verification=store.google_site_verification,
        bing_site_verification=store.bing_site_verification,
        meta_pixel_id=store.meta_pixel_id,
        has_meta_capi_token=bool(store.meta_capi_token and store.meta_capi_token.strip()),
        meta_test_event_code=store.meta_test_event_code,
        gtm_id=store.gtm_id,
        ga4_measurement_id=store.ga4_measurement_id,
        tiktok_pixel_id=store.tiktok_pixel_id,
        created_at=store.created_at,
        updated_at=store.updated_at,
    )


def _store_to_public(store: DropshipperStore) -> PublicStorefrontRead:
    """Strictly scrubbed public storefront payload. NEVER includes secrets or wholesale data."""
    return PublicStorefrontRead(
        slug=store.slug,
        template_id=StoreTemplateId(store.template_id),
        theme_config=StoreThemeConfig.model_validate(store.theme_config or {}),
        brand_config=StoreBrandConfig.model_validate(store.brand_config or {}),
        hero_config=StoreHeroConfig.model_validate(store.hero_config or {}),
        sections_config=[
            StoreSectionConfig.model_validate(s) for s in (store.sections_config or [])
        ],
        seo_title=store.seo_title,
        seo_description=store.seo_description,
        seo_og_image_url=store.seo_og_image_url,
        google_site_verification=store.google_site_verification,
        bing_site_verification=store.bing_site_verification,
        meta_pixel_id=store.meta_pixel_id,
        gtm_id=store.gtm_id,
        ga4_measurement_id=store.ga4_measurement_id,
        tiktok_pixel_id=store.tiktok_pixel_id,
    )


async def _get_or_provision_store_row(db: AsyncSession, user: User) -> DropshipperStore:
    store = (
        await db.execute(select(DropshipperStore).where(DropshipperStore.dropshipper_id == user.id))
    ).scalar_one_or_none()
    if store is not None:
        return store

    profile = (
        await db.execute(select(DropshipperProfile).where(DropshipperProfile.user_id == user.id))
    ).scalar_one_or_none()
    if profile is None or profile.status != DropshipperStatus.APPROVED.value:
        raise PermissionDeniedError("Only approved dropshippers can manage a storefront")

    slug = await _unique_store_slug(db, profile.shop_slug or profile.shop_name)
    store = DropshipperStore(
        dropshipper_id=user.id,
        profile_id=profile.id,
        slug=slug,
        is_published=False,
        template_id=StoreTemplateId.MODERN_TECH.value,
        theme_config=StoreThemeConfig().model_dump(),
        brand_config=StoreBrandConfig(
            shop_name=profile.shop_name,
            tagline=f"Welcome to {profile.shop_name}",
            logo_url=profile.shop_logo_url,
            phone=profile.shop_phone,
            whatsapp=profile.shop_phone,
            address=profile.shop_address,
            facebook_url=profile.business_url,
            announcement_text="Cash on Delivery available nationwide!",
            announcement_enabled=True,
        ).model_dump(),
        hero_config=StoreHeroConfig(
            title=f"Shop Quality Products at {profile.shop_name}",
            subtitle="Fast nationwide delivery with Cash on Delivery.",
            cta_text="Explore Products",
            cta_href="#products",
        ).model_dump(),
        sections_config=_default_sections(),
        seo_title=profile.shop_name[:120],
        seo_description=(
            f"Shop online from {profile.shop_name} with fast delivery across Bangladesh."
        ),
    )
    db.add(store)
    await db.commit()
    await db.refresh(store)
    return store


async def get_my_store(db: AsyncSession, user: User) -> DropshipperStoreRead:
    store = await _get_or_provision_store_row(db, user)
    return _store_to_read(store)


async def update_my_store(
    db: AsyncSession,
    user: User,
    payload: DropshipperStoreUpdate,
) -> DropshipperStoreRead:
    store = await _get_or_provision_store_row(db, user)

    if payload.slug is not None and payload.slug != store.slug:
        conflict = await db.scalar(
            select(DropshipperStore.id).where(
                DropshipperStore.slug == payload.slug,
                DropshipperStore.id != store.id,
            )
        )
        if conflict is not None:
            raise ConflictError(f"Store slug '{payload.slug}' is already taken")
        store.slug = payload.slug

    if payload.is_published is not None:
        store.is_published = payload.is_published
    if payload.template_id is not None:
        store.template_id = payload.template_id.value
    if payload.theme_config is not None:
        store.theme_config = payload.theme_config.model_dump()
    if payload.brand_config is not None:
        store.brand_config = payload.brand_config.model_dump()
    if payload.hero_config is not None:
        store.hero_config = payload.hero_config.model_dump()
    if payload.sections_config is not None:
        store.sections_config = [s.model_dump() for s in payload.sections_config]

    await db.commit()
    await db.refresh(store)
    return _store_to_read(store)


async def update_my_store_seo_tracking(
    db: AsyncSession,
    user: User,
    payload: DropshipperStoreSeoTrackingUpdate,
) -> DropshipperStoreRead:
    store = await _get_or_provision_store_row(db, user)
    data = payload.model_dump(exclude_unset=True)

    for field_name in (
        "seo_title",
        "seo_description",
        "seo_og_image_url",
        "google_site_verification",
        "bing_site_verification",
        "meta_pixel_id",
        "meta_test_event_code",
        "gtm_id",
        "ga4_measurement_id",
        "tiktok_pixel_id",
    ):
        if field_name in data:
            setattr(store, field_name, data[field_name])

    if "meta_capi_token" in data:
        token_val = data["meta_capi_token"]
        store.meta_capi_token = token_val if token_val else None

    await db.commit()
    await db.refresh(store)
    return _store_to_read(store)


def _validate_store_product_price(product: Product, selling_price: int) -> int:
    if not product.published or not product.allow_dropshipping or product.dropship_price is None:
        raise UnprocessableError(f"'{product.title}' is not eligible for dropshipping import")
    wholesale = int(product.dropship_price)
    if selling_price < wholesale:
        raise UnprocessableError(
            f"Selling price for '{product.title}' (৳{selling_price}) "
            f"cannot be below wholesale price (৳{wholesale})"
        )
    if product.min_sell_price is not None and selling_price < product.min_sell_price:
        raise UnprocessableError(
            f"Selling price for '{product.title}' must be at least ৳{product.min_sell_price}"
        )
    if product.max_sell_price is not None and selling_price > product.max_sell_price:
        raise UnprocessableError(
            f"Selling price for '{product.title}' cannot exceed ৳{product.max_sell_price}"
        )
    return wholesale


def _store_product_to_read(
    sp: DropshipperStoreProduct, product: Product
) -> DropshipperStoreProductRead:
    wholesale = int(product.dropship_price or 0)
    upstream_ok = bool(
        product.published
        and product.allow_dropshipping
        and product.status == StockStatus.AVAILABLE.value
        and product.dropship_price is not None
    )
    return DropshipperStoreProductRead(
        id=sp.id,
        store_id=sp.store_id,
        product_id=sp.product_id,
        product_slug=product.slug,
        title=sp.custom_title or product.title,
        custom_title=sp.custom_title,
        image_src=product.image_src,
        dropship_price=wholesale,
        min_sell_price=product.min_sell_price,
        max_sell_price=product.max_sell_price,
        selling_price=sp.selling_price,
        compare_at_price=sp.compare_at_price,
        estimated_profit=sp.selling_price - wholesale,
        stock_quantity=product.quantity,
        upstream_available=upstream_ok,
        is_featured=sp.is_featured,
        is_active=sp.is_active,
        sort_order=sp.sort_order,
        created_at=sp.created_at,
        updated_at=sp.updated_at,
    )


async def list_my_store_products(
    db: AsyncSession, user: User
) -> DropshipperStoreProductListResponse:
    store = await _get_or_provision_store_row(db, user)
    rows = (
        await db.execute(
            select(DropshipperStoreProduct, Product)
            .join(Product, Product.id == DropshipperStoreProduct.product_id)
            .where(DropshipperStoreProduct.store_id == store.id)
            .order_by(
                DropshipperStoreProduct.sort_order.asc(),
                DropshipperStoreProduct.created_at.desc(),
            )
        )
    ).all()
    items = [_store_product_to_read(sp, prod) for sp, prod in rows]
    return DropshipperStoreProductListResponse(items=items, total=len(items))


async def import_my_store_products(
    db: AsyncSession,
    user: User,
    payload: DropshipperStoreProductImportRequest,
) -> DropshipperStoreProductListResponse:
    store = await _get_or_provision_store_row(db, user)
    product_ids = list({it.product_id for it in payload.items})
    products = (await db.scalars(select(Product).where(Product.id.in_(product_ids)))).all()
    products_by_id = {p.id: p for p in products}

    existing_rows = (
        await db.scalars(
            select(DropshipperStoreProduct).where(
                DropshipperStoreProduct.store_id == store.id,
                DropshipperStoreProduct.product_id.in_(product_ids),
            )
        )
    ).all()
    existing_by_pid = {sp.product_id: sp for sp in existing_rows}

    for item in payload.items:
        product = products_by_id.get(item.product_id)
        if product is None:
            raise NotFoundError("Product not found")
        _validate_store_product_price(product, item.selling_price)

        existing = existing_by_pid.get(item.product_id)
        if existing is not None:
            existing.custom_title = item.custom_title
            existing.selling_price = item.selling_price
            existing.compare_at_price = item.compare_at_price
            existing.is_featured = item.is_featured
            existing.is_active = item.is_active
            existing.sort_order = item.sort_order
        else:
            db.add(
                DropshipperStoreProduct(
                    store_id=store.id,
                    product_id=item.product_id,
                    custom_title=item.custom_title,
                    selling_price=item.selling_price,
                    compare_at_price=item.compare_at_price,
                    is_featured=item.is_featured,
                    is_active=item.is_active,
                    sort_order=item.sort_order,
                )
            )

    await db.commit()
    return await list_my_store_products(db, user)


async def update_my_store_product(
    db: AsyncSession,
    user: User,
    store_product_id: uuid.UUID,
    payload: DropshipperStoreProductUpdate,
) -> DropshipperStoreProductRead:
    store = await _get_or_provision_store_row(db, user)
    row = (
        await db.execute(
            select(DropshipperStoreProduct, Product)
            .join(Product, Product.id == DropshipperStoreProduct.product_id)
            .where(
                DropshipperStoreProduct.id == store_product_id,
                DropshipperStoreProduct.store_id == store.id,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Store product not found")

    sp, product = row
    data = payload.model_dump(exclude_unset=True)
    if "selling_price" in data and data["selling_price"] is not None:
        _validate_store_product_price(product, int(data["selling_price"]))
        sp.selling_price = int(data["selling_price"])
    if "custom_title" in data:
        sp.custom_title = data["custom_title"]
    if "compare_at_price" in data:
        sp.compare_at_price = data["compare_at_price"]
    if "is_featured" in data and data["is_featured"] is not None:
        sp.is_featured = bool(data["is_featured"])
    if "is_active" in data and data["is_active"] is not None:
        sp.is_active = bool(data["is_active"])
    if "sort_order" in data and data["sort_order"] is not None:
        sp.sort_order = int(data["sort_order"])

    await db.commit()
    await db.refresh(sp)
    return _store_product_to_read(sp, product)


async def delete_my_store_product(
    db: AsyncSession,
    user: User,
    store_product_id: uuid.UUID,
) -> None:
    store = await _get_or_provision_store_row(db, user)
    sp = (
        await db.execute(
            select(DropshipperStoreProduct).where(
                DropshipperStoreProduct.id == store_product_id,
                DropshipperStoreProduct.store_id == store.id,
            )
        )
    ).scalar_one_or_none()
    if sp is None:
        raise NotFoundError("Store product not found")
    await db.delete(sp)
    await db.commit()


# ---------------------------------------------------------------------------
# Public Multi-Tenant Storefront & Checkout (ZERO AUTH, ZERO SECRET LEAKAGE)
# ---------------------------------------------------------------------------


async def _get_published_store_by_slug(
    db: AsyncSession, slug: str
) -> tuple[DropshipperStore, DropshipperProfile, User]:
    row = (
        await db.execute(
            select(DropshipperStore, DropshipperProfile, User)
            .join(DropshipperProfile, DropshipperProfile.id == DropshipperStore.profile_id)
            .join(User, User.id == DropshipperStore.dropshipper_id)
            .where(
                DropshipperStore.slug == slug.strip().lower(),
                DropshipperStore.is_published.is_(True),
                DropshipperProfile.status == DropshipperStatus.APPROVED.value,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Store not found")
    return row[0], row[1], row[2]


async def public_get_store(db: AsyncSession, slug: str) -> PublicStorefrontRead:
    store, _profile, _owner = await _get_published_store_by_slug(db, slug)
    return _store_to_public(store)


def _extract_media(product: Product) -> list[PublicStoreMediaItem]:
    items: list[PublicStoreMediaItem] = []
    if product.image_src:
        items.append(PublicStoreMediaItem(kind="image", url=product.image_src, alt=product.title))
    content = product.content if isinstance(product.content, dict) else {}
    gallery = content.get("gallery")
    if isinstance(gallery, list):
        for g in gallery:
            if not isinstance(g, dict):
                continue
            kind = g.get("kind")
            if kind == "youtube" and g.get("youtube_id"):
                items.append(
                    PublicStoreMediaItem(
                        kind="youtube",
                        url="",
                        youtube_id=str(g.get("youtube_id") or ""),
                        thumbnail=str(g.get("thumbnail") or ""),
                        alt=str(g.get("alt") or ""),
                    )
                )
            elif g.get("src"):
                items.append(
                    PublicStoreMediaItem(
                        kind="video" if kind == "video" else "image",
                        url=str(g.get("src")),
                        thumbnail=str(g.get("thumbnail") or ""),
                        alt=str(g.get("alt") or ""),
                    )
                )
    return items


def _to_public_product(
    sp: DropshipperStoreProduct,
    product: Product,
    category: Category | None,
    variants: list[ProductVariant],
) -> PublicStoreProductRead:
    content = product.content if isinstance(product.content, dict) else {}
    description = str(content.get("description") or "")
    in_stock = product.status == StockStatus.AVAILABLE.value and (
        product.quantity is None or product.quantity > 0
    )
    return PublicStoreProductRead(
        id=sp.id,
        product_id=product.id,
        slug=product.slug,
        title=sp.custom_title or product.title,
        subtitle=product.subtitle or "",
        description=description,
        category_slug=category.slug if category else "",
        category_name=category.name if category else "",
        selling_price=sp.selling_price,
        compare_at_price=sp.compare_at_price,
        stock_quantity=product.quantity,
        in_stock=in_stock,
        weight_grams=product.weight_grams,
        has_variants=bool(product.has_variants),
        is_featured=sp.is_featured,
        image_src=product.image_src,
        media=_extract_media(product),
        variants=[
            PublicStoreVariantRead(
                id=v.id,
                options=v.options or {},
                label=" / ".join((v.options or {}).values()),
                sku=v.sku or "",
                selling_price=sp.selling_price,
                stock_quantity=v.quantity,
                weight_grams=v.weight_grams,
                is_active=v.is_active,
            )
            for v in variants
            if v.is_active
        ],
    )


async def public_list_products(
    db: AsyncSession,
    slug: str,
    *,
    q: str | None = None,
    category: str | None = None,
    featured: bool | None = None,
    page: int = 1,
    page_size: int = 24,
) -> PublicStoreProductListResponse:
    store, _profile, _owner = await _get_published_store_by_slug(db, slug)

    conds: list[Any] = [
        DropshipperStoreProduct.store_id == store.id,
        DropshipperStoreProduct.is_active.is_(True),
        Product.published.is_(True),
        Product.allow_dropshipping.is_(True),
        Product.status == StockStatus.AVAILABLE.value,
        Product.dropship_price.is_not(None),
    ]
    if featured is True:
        conds.append(DropshipperStoreProduct.is_featured.is_(True))
    if category and category.strip():
        conds.append(Category.slug == category.strip().lower())
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        conds.append(
            func.lower(Product.title).like(term)
            | func.lower(func.coalesce(DropshipperStoreProduct.custom_title, "")).like(term)
        )

    total = int(
        await db.scalar(
            select(func.count(DropshipperStoreProduct.id))
            .select_from(DropshipperStoreProduct)
            .join(Product, Product.id == DropshipperStoreProduct.product_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .where(*conds)
        )
        or 0
    )

    rows = (
        await db.execute(
            select(DropshipperStoreProduct, Product, Category)
            .join(Product, Product.id == DropshipperStoreProduct.product_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .where(*conds)
            .order_by(
                DropshipperStoreProduct.is_featured.desc(),
                DropshipperStoreProduct.sort_order.asc(),
                DropshipperStoreProduct.created_at.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    pids = [prod.id for _sp, prod, _cat in rows]
    variants_by_pid: dict[uuid.UUID, list[ProductVariant]] = {}
    if pids:
        variants = (
            await db.scalars(select(ProductVariant).where(ProductVariant.product_id.in_(pids)))
        ).all()
        for v in variants:
            variants_by_pid.setdefault(v.product_id, []).append(v)

    items = [
        _to_public_product(sp, prod, cat, variants_by_pid.get(prod.id, []))
        for sp, prod, cat in rows
    ]
    return PublicStoreProductListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def public_get_product(
    db: AsyncSession, slug: str, product_slug: str
) -> PublicStoreProductRead:
    store, _profile, _owner = await _get_published_store_by_slug(db, slug)
    row = (
        await db.execute(
            select(DropshipperStoreProduct, Product, Category)
            .join(Product, Product.id == DropshipperStoreProduct.product_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .where(
                DropshipperStoreProduct.store_id == store.id,
                DropshipperStoreProduct.is_active.is_(True),
                Product.slug == product_slug,
                Product.published.is_(True),
                Product.allow_dropshipping.is_(True),
                Product.status == StockStatus.AVAILABLE.value,
                Product.dropship_price.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Product not found")
    sp, prod, cat = row
    variants = list(
        (await db.scalars(select(ProductVariant).where(ProductVariant.product_id == prod.id))).all()
    )
    return _to_public_product(sp, prod, cat, variants)


async def _resolve_public_items(
    db: AsyncSession,
    store: DropshipperStore,
    req: PublicStoreOrderQuoteRequest,
) -> list[DropshipOrderItemInput]:
    pids = list({it.product_id for it in req.items})
    store_products = (
        await db.scalars(
            select(DropshipperStoreProduct).where(
                DropshipperStoreProduct.store_id == store.id,
                DropshipperStoreProduct.product_id.in_(pids),
                DropshipperStoreProduct.is_active.is_(True),
            )
        )
    ).all()
    by_pid = {sp.product_id: sp for sp in store_products}

    resolved: list[DropshipOrderItemInput] = []
    for item in req.items:
        sp = by_pid.get(item.product_id)
        if sp is None:
            raise UnprocessableError("One or more items are not available in this store")
        resolved.append(
            DropshipOrderItemInput(
                product_id=item.product_id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                selling_price=sp.selling_price,
            )
        )
    return resolved


async def public_quote_order(
    db: AsyncSession,
    slug: str,
    payload: PublicStoreOrderQuoteRequest,
) -> PublicStoreOrderQuoteResponse:
    store, _profile, owner = await _get_published_store_by_slug(db, slug)
    resolved_items = await _resolve_public_items(db, store, payload)
    quote = await dropship_order_service.quote_order(
        db,
        owner,
        DropshipOrderQuoteRequest(
            items=resolved_items,
            district=payload.district,
            area=payload.area,
            delivery_zone=payload.delivery_zone,
        ),
    )
    return PublicStoreOrderQuoteResponse(
        lines=[
            PublicStoreOrderQuoteLine(
                product_id=line.product_id,
                variant_id=line.variant_id,
                title=line.title,
                slug=line.slug,
                image_src=line.image_src,
                quantity=line.quantity,
                unit_price=line.selling_price,
                line_total=line.selling_total,
            )
            for line in quote.lines
        ],
        delivery_zone=quote.delivery_zone,
        total_weight_grams=quote.total_weight_grams,
        subtotal=quote.customer_subtotal,
        shipping=quote.shipping,
        total=quote.customer_total,
    )


async def public_create_order(
    db: AsyncSession,
    slug: str,
    payload: PublicStoreOrderCreateRequest,
    idempotency_key: str,
    background: BackgroundTasks | None = None,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> PublicStoreOrderCreateResponse:
    store, _profile, owner = await _get_published_store_by_slug(db, slug)
    pixel_id = store.meta_pixel_id
    capi_token = store.meta_capi_token
    test_event_code = store.meta_test_event_code
    resolved_items = await _resolve_public_items(db, store, payload)

    created = await dropship_order_service.create_order(
        db,
        owner,
        DropshipOrderCreateRequest(
            items=resolved_items,
            district=payload.district,
            area=payload.area,
            delivery_zone=payload.delivery_zone,
            customer_name=payload.customer_name,
            phone=payload.phone,
            address=payload.address,
            note=payload.note,
        ),
        idempotency_key=idempotency_key,
        background=background,
    )

    event_id = purchase_event_id(created.number)
    if background is not None and pixel_id and capi_token and capi_token.strip():
        loaded_order = (
            await db.execute(
                select(Order).options(selectinload(Order.items)).where(Order.id == created.id)
            )
        ).scalar_one_or_none()
        if loaded_order is not None:
            meta_capi.schedule_custom_purchase(
                background,
                loaded_order,
                payload.tracking,
                pixel_id=pixel_id,
                access_token=capi_token,
                test_event_code=test_event_code,
                client_ip=client_ip,
                user_agent=user_agent,
            )

    return PublicStoreOrderCreateResponse(
        order_number=created.number,
        analytics_event_id=event_id,
        status=created.status,
        subtotal=created.customer_subtotal,
        shipping=created.shipping,
        total=created.customer_total,
        created_at=created.created_at,
    )
