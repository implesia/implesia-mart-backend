import json
import re
import uuid
from typing import Any

from fastapi import UploadFile
from pydantic import ValidationError
from slugify import slugify
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.audit_event import AuditAction
from app.models.category import Category
from app.models.product import Product, ProductBadge, ProductVariant, StockStatus
from app.models.user import User
from app.schemas.common import page_count
from app.schemas.product import (
    SLUG_PATTERN,
    AdminProductCard,
    AdminProductList,
    AdminProductMetrics,
    AdminProductQuery,
    AdminProductRead,
    AvailabilityCounts,
    CatalogQuery,
    CategoryCounts,
    GalleryImage,
    ProductContent,
    ProductCreate,
    ProductUpdate,
    PublicCategoryCounts,
    PublicFaq,
    PublicGalleryImage,
    PublicOptionGroup,
    PublicOptionValue,
    PublicProductCard,
    PublicProductDetail,
    PublicProductList,
    PublicSpec,
)
from app.services import audit_service, category_service, variant_service
from app.services.category_service import CategoryIndex
from app.services.image_storage import (
    delete_owned_media,
    owned_refs,
    read_image,
    real_uploads,
    store_image,
)

_SLUG = re.compile(SLUG_PATTERN)
_CONTENT_LIMIT = 100_000
_RELATED_LIMIT = 8

_Expr = ColumnElement[Any]


def slug_from_title(title: str) -> str:
    raw = slugify(title, max_length=140, lowercase=True)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if _SLUG.fullmatch(raw):
        return raw
    # Bengali titles have no ASCII slug. Callers append a numeric suffix.
    return "product"


def _prices_ok(price: int, compare_at_price: int | None) -> None:
    if compare_at_price is not None and compare_at_price < price:
        raise UnprocessableError("Compare-at price must be at least the selling price")


def _split_content(content: ProductContent, *, title: str) -> tuple[str, str, dict[str, Any]]:
    stored = content.model_dump(mode="json")
    unit_label = str(stored.pop("unit_label"))
    image_alt = str(stored.pop("image_alt")) or title
    encoded = json.dumps(stored, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _CONTENT_LIMIT:
        raise UnprocessableError("Product details are too large")
    return unit_label, image_alt, stored


def _search(term: str) -> _Expr:
    # Escape LIKE wildcards so a search for "%" cannot scan the whole catalog.
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    haystack = func.lower(
        Product.title + literal(" ") + Product.subtitle + literal(" ") + Product.slug
    )
    in_category = Product.category_id.in_(
        select(Category.id).where(func.lower(Category.name).like(f"%{escaped}%", escape="\\"))
    )
    return or_(haystack.like(f"%{escaped}%", escape="\\"), in_category)


def _apply(stmt: Any, conditions: list[_Expr]) -> Any:
    if conditions:
        return stmt.where(*conditions)
    return stmt


async def _count(db: AsyncSession, conditions: list[_Expr]) -> int:
    stmt = _apply(select(func.count()).select_from(Product), conditions)
    return int(await db.scalar(stmt) or 0)


async def allocate_slug(db: AsyncSession, title: str) -> str:
    base = slug_from_title(title)[:140].strip("-") or "product"
    candidate = base
    for number in range(2, 100):
        taken = await db.scalar(select(Product.id).where(Product.slug == candidate).limit(1))
        if taken is None:
            return candidate
        suffix = f"-{number}"
        candidate = f"{base[: 160 - len(suffix)]}{suffix}".strip("-")
    return f"product-{uuid.uuid4().hex[:10]}"


async def get_by_id(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found")
    return product


async def _saved_images(
    files: list[UploadFile], alts: list[str], fallback_alt: str
) -> list[GalleryImage]:
    uploads = real_uploads(files)
    saved: list[str] = []
    try:
        images: list[GalleryImage] = []
        for index, upload in enumerate(uploads):
            data = await read_image(upload)
            url = store_image(data)
            saved.append(url)
            alt = alts[index] if index < len(alts) and alts[index] else fallback_alt
            images.append(GalleryImage(src=url, alt=alt))
        return images
    except ValidationError as exc:
        delete_owned_media(set(saved))
        raise UnprocessableError("Image text is invalid") from exc
    except Exception:
        delete_owned_media(set(saved))
        raise


def _media_refs(product: Product) -> set[str]:
    content = content_of(product)
    return owned_refs(
        product.image_src,
        content.quality_image_src,
        *(item.src for item in content.gallery),
    )


async def create_product(
    db: AsyncSession,
    payload: ProductCreate,
    images: list[UploadFile] | None = None,
    image_alts: list[str] | None = None,
    quality_image: UploadFile | None = None,
    quality_image_alt: str = "",
) -> Product:
    fallback_alt = payload.content.image_alt or payload.title
    added: list[GalleryImage] = []
    quality_url = ""
    try:
        added = await _saved_images(images or [], image_alts or [], fallback_alt)
        if quality_image is not None and quality_image.filename:
            saved = await _saved_images([quality_image], [quality_image_alt], fallback_alt)
            quality_url = saved[0].src
            if not quality_image_alt:
                quality_image_alt = saved[0].alt
        gallery = [*payload.content.gallery, *added]
        if len(gallery) > 12:
            raise UnprocessableError("A product can have at most 12 images")
        image_src = payload.image_src or (gallery[0].src if gallery else "")
        if not image_src:
            raise UnprocessableError("Add a product image")
        payload = payload.model_copy(
            update={
                "image_src": image_src,
                "content": payload.content.model_copy(
                    update={
                        "gallery": gallery,
                        "quality_image_src": quality_url or payload.content.quality_image_src,
                        "quality_image_alt": quality_image_alt or payload.content.quality_image_alt,
                    }
                ),
            }
        )
        return await _insert_product(db, payload)
    except Exception:
        delete_owned_media(owned_refs(*(item.src for item in added), quality_url))
        raise


async def _insert_product(db: AsyncSession, payload: ProductCreate) -> Product:
    if payload.slug:
        taken = await db.scalar(select(Product.id).where(Product.slug == payload.slug).limit(1))
        if taken is not None:
            raise ConflictError("A product with this slug already exists")
        slug = payload.slug
    else:
        slug = await allocate_slug(db, payload.title)

    category = await category_service.resolve_for_product(
        db, category_id=payload.category_id, legacy_slug=payload.category
    )
    unit_label, image_alt, stored = _split_content(payload.content, title=payload.title)
    sort_order = int(await db.scalar(select(func.max(Product.sort_order))) or 0) + 1
    product = Product(
        slug=slug,
        title=payload.title,
        subtitle=payload.subtitle,
        category_id=category.id,
        price=payload.price,
        compare_at_price=payload.compare_at_price,
        quantity=payload.quantity,
        status=payload.status.value,
        badge=payload.badge.value if payload.badge else None,
        image_src=payload.image_src,
        image_alt=image_alt,
        unit_label=unit_label,
        featured=payload.featured,
        published=payload.published,
        sort_order=sort_order,
        content=stored,
        min_order_quantity=payload.min_order_quantity,
        max_order_quantity=payload.max_order_quantity,
    )
    db.add(product)
    try:
        if payload.variants:
            await db.flush()
            await variant_service.save_variants(
                db, product, payload.content, payload.variants, explicit_status=True
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A product with this slug already exists") from exc
    except Exception:
        await db.rollback()
        raise
    await db.refresh(product)
    return product


async def update_product(
    db: AsyncSession,
    product: Product,
    payload: ProductUpdate,
    images: list[UploadFile] | None = None,
    image_alts: list[str] | None = None,
    quality_image: UploadFile | None = None,
    quality_image_alt: str = "",
    *,
    actor: User,
) -> Product:
    before = _media_refs(product)
    fallback_alt = (
        payload.content.image_alt
        if payload.content is not None and payload.content.image_alt
        else product.image_alt or product.title
    )
    added: list[GalleryImage] = []
    quality_url = ""
    try:
        added = await _saved_images(images or [], image_alts or [], fallback_alt)
        if quality_image is not None and quality_image.filename:
            saved = await _saved_images([quality_image], [quality_image_alt], fallback_alt)
            quality_url = saved[0].src
        await _apply_update(db, product, payload, added, quality_url, quality_image_alt, actor)
    except Exception:
        delete_owned_media(owned_refs(*(item.src for item in added), quality_url))
        raise
    delete_owned_media(before - _media_refs(product))
    return product


async def _apply_update(
    db: AsyncSession,
    product: Product,
    payload: ProductUpdate,
    added: list[GalleryImage],
    quality_url: str,
    quality_image_alt: str,
    actor: User,
) -> None:
    before = {
        "price": product.price,
        "compare_at_price": product.compare_at_price,
        "quantity": product.quantity,
        "status": product.status,
    }
    fields = payload.model_dump(
        exclude_unset=True, exclude={"content", "category", "category_id", "variants"}
    )
    if fields.get("min_order_quantity", 0) is None:
        fields.pop("min_order_quantity")
    new_min = int(fields.get("min_order_quantity", product.min_order_quantity))
    new_max = fields.get("max_order_quantity", product.max_order_quantity)
    if new_max is not None and int(new_max) < new_min:
        raise UnprocessableError("Maximum order quantity must be at least the minimum")
    if payload.category_id is not None or payload.category is not None:
        target = await category_service.resolve_for_product(
            db, category_id=payload.category_id, legacy_slug=payload.category
        )
        product.category_id = target.id
    price = fields.get("price", product.price)
    if "compare_at_price" in fields:
        compare_at_price = fields["compare_at_price"]
    else:
        compare_at_price = product.compare_at_price
    _prices_ok(int(price), compare_at_price)

    title = str(fields.get("title", product.title))
    for field, value in fields.items():
        if isinstance(value, StockStatus | ProductBadge):
            value = value.value
        setattr(product, field, value)

    has_content = "content" in payload.model_fields_set and payload.content is not None
    if added or quality_url or quality_image_alt or has_content:
        content = content_of(product)
        if has_content and payload.content is not None:
            content = payload.content
        gallery = [*content.gallery, *added]
        if len(gallery) > 12:
            raise UnprocessableError("A product can have at most 12 images")
        updates: dict[str, Any] = {"gallery": gallery}
        if quality_url:
            updates["quality_image_src"] = quality_url
        if quality_image_alt:
            updates["quality_image_alt"] = quality_image_alt
        content = content.model_copy(update=updates)
        unit_label, image_alt, stored = _split_content(content, title=title)
        product.unit_label = unit_label
        product.image_alt = image_alt
        product.content = stored
        if not product.image_src and gallery:
            product.image_src = gallery[0].src

    if payload.variants is not None:
        await variant_service.save_variants(
            db,
            product,
            content_of(product),
            payload.variants,
            explicit_status="status" in payload.model_fields_set,
        )
    elif has_content:
        await variant_service.ensure_still_valid(db, product, content_of(product))

    await _audit_catalog_changes(db, product, actor, before)
    await db.commit()
    await db.refresh(product)


async def _audit_catalog_changes(
    db: AsyncSession,
    product: Product,
    actor: User,
    before: dict[str, Any],
) -> None:
    price_changes = _field_changes(before, product, ("price", "compare_at_price"))
    if price_changes:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.PRODUCT_PRICE_UPDATED,
            target_type="product",
            target_id=product.id,
            metadata=price_changes,
        )
    stock_changes = _field_changes(before, product, ("quantity", "status"))
    if stock_changes:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.PRODUCT_STOCK_UPDATED,
            target_type="product",
            target_id=product.id,
            metadata=stock_changes,
        )


def _field_changes(
    before: dict[str, Any], product: Product, fields: tuple[str, ...]
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for field in fields:
        current = getattr(product, field)
        if current == before[field]:
            continue
        changes[field] = {"from": before[field], "to": current}
    return changes


async def delete_product(db: AsyncSession, product: Product) -> None:
    refs = _media_refs(product)
    await db.delete(product)
    await db.commit()
    delete_owned_media(refs)


def _admin_order(sort: str) -> tuple[Any, ...]:
    stable = (Product.sort_order.asc(), Product.id.asc())
    if sort == "name-asc":
        return (Product.title.asc(), *stable)
    if sort == "name-desc":
        return (Product.title.desc(), *stable)
    if sort == "price-asc":
        return (Product.price.asc(), *stable)
    if sort == "price-desc":
        return (Product.price.desc(), *stable)
    if sort == "stock-asc":
        rank = case(
            (Product.status == StockStatus.SOLD_OUT.value, 0),
            (Product.quantity.is_(None), 2),
            else_=1,
        )
        return (rank.asc(), Product.quantity.asc().nulls_last(), *stable)
    if sort == "stock-desc":
        rank = case(
            (
                (Product.quantity.is_(None)) & (Product.status != StockStatus.SOLD_OUT.value),
                0,
            ),
            (Product.status == StockStatus.SOLD_OUT.value, 2),
            else_=1,
        )
        return (rank.asc(), Product.quantity.desc().nulls_first(), *stable)
    return (Product.sort_order.asc(), Product.created_at.asc(), Product.id.asc())


def _public_order(sort: str) -> tuple[Any, ...]:
    stable = (Product.sort_order.asc(), Product.id.asc())
    if sort == "price-asc":
        return (Product.price.asc(), *stable)
    if sort == "price-desc":
        return (Product.price.desc(), *stable)
    if sort == "newest":
        return (Product.created_at.desc(), Product.id.desc())
    rank = case(
        (Product.badge == ProductBadge.BEST_SELLER.value, 0),
        (Product.badge == ProductBadge.NEW.value, 1),
        (Product.status == StockStatus.AVAILABLE.value, 2),
        else_=3,
    )
    return (rank.asc(), *stable)


def _admin_scope(index: CategoryIndex, query: AdminProductQuery) -> list[uuid.UUID] | None:
    """Category ids an admin list is limited to. The admin sees hidden categories too."""
    if query.category_id is None and query.category is None:
        return None
    row = (
        index.by_id.get(query.category_id)
        if query.category_id is not None
        else index.by_slug.get(query.category or "")
    )
    if row is None:
        return []
    return index.descendants(row.id) if query.include_descendants else [row.id]


def _admin_filters(
    query: AdminProductQuery, *, scope: list[uuid.UUID] | None, search: bool
) -> list[_Expr]:
    conditions: list[_Expr] = []
    if scope is not None:
        conditions.append(Product.category_id.in_(scope))
    if query.status is not None:
        conditions.append(Product.status == query.status.value)
    if query.visibility == "live":
        conditions.append(Product.published.is_(True))
    elif query.visibility == "hidden":
        conditions.append(Product.published.is_(False))
    if query.min_price is not None:
        conditions.append(Product.price >= query.min_price)
    if query.max_price is not None:
        conditions.append(Product.price <= query.max_price)
    if search and query.q:
        conditions.append(_search(query.q))
    return conditions


def _public_filters(
    query: CatalogQuery,
    *,
    index: CategoryIndex,
    ignore: frozenset[str] = frozenset(),
) -> list[_Expr]:
    conditions: list[_Expr] = [Product.published.is_(True)]
    # Products of a hidden (inactive, or under an inactive ancestor) category are not public.
    hidden = index.hidden_ids()
    if hidden:
        conditions.append(Product.category_id.notin_(hidden))
    if "category" not in ignore:
        scope = category_service.listing_scope(
            index,
            slug=query.category,
            category_id=query.category_id,
            descendants=query.include_descendants,
        )
        if scope is not None:
            conditions.append(Product.category_id.in_(scope))
    if "status" not in ignore and query.statuses:
        conditions.append(Product.status.in_(query.statuses))
    if "price" not in ignore and query.min_price is not None:
        conditions.append(Product.price >= query.min_price)
    if "price" not in ignore and query.max_price is not None:
        conditions.append(Product.price <= query.max_price)
    if "view" not in ignore and query.view == "featured":
        conditions.append(Product.featured.is_(True))
    if "view" not in ignore and query.view == "new":
        conditions.append(Product.badge == ProductBadge.NEW.value)
    if "badge" not in ignore and query.badge is not None:
        conditions.append(Product.badge == query.badge.value)
    return conditions


async def _metrics(db: AsyncSession, scope: list[uuid.UUID] | None) -> AdminProductMetrics:
    conditions: list[_Expr] = []
    if scope is not None:
        conditions.append(Product.category_id.in_(scope))
    stmt = _apply(
        select(
            func.count(),
            func.coalesce(func.sum(case((Product.published.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Product.published.is_(False), 1), else_=0)), 0),
            func.coalesce(
                func.sum(case((Product.status == StockStatus.SOLD_OUT.value, 1), else_=0)),
                0,
            ),
        ).select_from(Product),
        conditions,
    )
    total, live, hidden, sold_out = (await db.execute(stmt)).one()
    return AdminProductMetrics(
        total=int(total or 0),
        live=int(live or 0),
        hidden=int(hidden or 0),
        sold_out=int(sold_out or 0),
    )


async def _category_counts(
    db: AsyncSession, conditions: list[_Expr], index: CategoryIndex
) -> dict[str, int]:
    """Products per legacy top-level category (`gadgets`, `fashion`) plus `all`.

    A top-level count includes everything below it, so the old two-tab filter keeps its meaning.
    """
    stmt = _apply(
        select(Product.category_id, func.count()).group_by(Product.category_id), conditions
    )
    direct = {cid: int(total) for cid, total in (await db.execute(stmt)).all()}
    rolled = category_service.rollup(index, direct)
    counts = {"all": sum(direct.values()), "gadgets": 0, "fashion": 0}
    for slug in ("gadgets", "fashion"):
        row = index.by_slug.get(slug)
        if row is not None:
            counts[slug] = rolled.get(row.id, 0)
    return counts


def _root_slug(index: CategoryIndex, category_id: uuid.UUID) -> str:
    root = index.root_of(category_id)
    return root.slug if root is not None else ""


def _category_fields(index: CategoryIndex, product: Product) -> dict[str, Any]:
    row = index.by_id.get(product.category_id)
    return {
        "category": _root_slug(index, product.category_id),
        "category_id": product.category_id,
        "category_slug": row.slug if row is not None else "",
        "category_name": row.name if row is not None else "",
    }


def admin_card(product: Product, index: CategoryIndex) -> AdminProductCard:
    return AdminProductCard(
        id=product.id,
        slug=product.slug,
        title=product.title,
        subtitle=product.subtitle,
        **_category_fields(index, product),
        category_path=category_service.refs(index, product.category_id),
        price=product.price,
        compare_at_price=product.compare_at_price,
        quantity=product.quantity,
        status=StockStatus(product.status),
        badge=ProductBadge(product.badge) if product.badge else None,
        image_src=product.image_src,
        featured=product.featured,
        published=product.published,
        has_variants=product.has_variants,
        created_at=product.created_at,
    )


def content_of(product: Product) -> ProductContent:
    raw = dict(product.content or {})
    raw["unit_label"] = product.unit_label
    raw["image_alt"] = product.image_alt
    return ProductContent.model_validate(raw)


def admin_read(
    product: Product, index: CategoryIndex, variants: list[ProductVariant] | None = None
) -> AdminProductRead:
    content = content_of(product)
    return AdminProductRead(
        **admin_card(product, index).model_dump(),
        content=content,
        min_order_quantity=product.min_order_quantity,
        max_order_quantity=product.max_order_quantity,
        variants=variant_service.admin_read(content, variants or []),
        updated_at=product.updated_at,
    )


async def admin_read_full(
    db: AsyncSession, product: Product, index: CategoryIndex
) -> AdminProductRead:
    return admin_read(product, index, await variant_service.list_variants(db, product.id))


def public_card(product: Product, index: CategoryIndex) -> PublicProductCard:
    return PublicProductCard(
        id=product.id,
        slug=product.slug,
        title=product.title,
        subtitle=product.subtitle,
        **_category_fields(index, product),
        price=product.price,
        compare_at_price=product.compare_at_price,
        unit_label=product.unit_label,
        image_src=product.image_src,
        image_alt=product.image_alt,
        badge=ProductBadge(product.badge) if product.badge else None,
        status=StockStatus(product.status),
        featured=product.featured,
        has_variants=product.has_variants,
    )


def public_detail(
    product: Product,
    related: list[Product],
    index: CategoryIndex,
    variants: list[ProductVariant] | None = None,
) -> PublicProductDetail:
    content = content_of(product)
    gallery = [
        PublicGalleryImage(src=item.src, alt=item.alt or product.title) for item in content.gallery
    ]
    if not gallery and product.image_src:
        gallery = [
            PublicGalleryImage(src=product.image_src, alt=product.image_alt or product.title)
        ]
    return PublicProductDetail(
        **public_card(product, index).model_dump(),
        category_path=category_service.refs(index, product.category_id),
        tagline=content.tagline,
        description=content.description,
        stock_label=content.stock_label,
        gallery=gallery,
        highlights=content.highlights,
        suitable_for=content.suitable_for,
        package_items=content.package_items,
        how_to_use=content.how_to_use,
        story_heading=content.story_heading,
        story_body=content.story_body,
        story_bullets=content.story_bullets,
        quality_title=content.quality_title,
        quality_body=content.quality_body,
        quality_image_src=content.quality_image_src,
        quality_image_alt=content.quality_image_alt,
        specs=[
            PublicSpec(label=item.label, value=item.value, group=item.group)
            for item in content.specs
        ],
        faqs=[PublicFaq(question=item.question, answer=item.answer) for item in content.faqs],
        options=[
            PublicOptionGroup(
                id=group.id,
                name=group.name,
                kind=group.kind,
                values=[
                    PublicOptionValue(id=value.id, label=value.label, swatch=value.swatch)
                    for value in group.values
                ],
            )
            for group in content.options
        ],
        variants=variant_service.public_read(product, content, variants or []),
        min_per_order=variant_service.order_limits(product)[0],
        max_per_order=variant_service.order_limits(product)[1],
        related=[public_card(item, index) for item in related],
    )


async def list_admin(db: AsyncSession, query: AdminProductQuery) -> AdminProductList:
    index = await category_service.load_index(db)
    scope = _admin_scope(index, query)
    conditions = _admin_filters(query, scope=scope, search=True)
    total = await _count(db, conditions)
    stmt = (
        _apply(select(Product), conditions)
        .options(defer(Product.content))
        .order_by(*_admin_order(query.sort))
        .offset(query.offset)
        .limit(query.page_size)
    )
    rows: list[Product] = list((await db.execute(stmt)).scalars().all())
    counts = await _category_counts(db, _admin_filters(query, scope=None, search=False), index)
    return AdminProductList(
        items=[admin_card(product, index) for product in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=page_count(total, query.page_size),
        metrics=await _metrics(db, scope),
        category_counts=CategoryCounts(
            all=counts["all"],
            gadgets=counts["gadgets"],
            fashion=counts["fashion"],
        ),
    )


async def list_public(db: AsyncSession, query: CatalogQuery) -> PublicProductList:
    index = await category_service.load_index(db)
    conditions = _public_filters(query, index=index)
    total = await _count(db, conditions)
    stmt = (
        _apply(select(Product), conditions)
        .options(defer(Product.content))
        .order_by(*_public_order(query.sort))
        .offset(query.offset)
        .limit(query.page_size)
    )
    rows: list[Product] = list((await db.execute(stmt)).scalars().all())
    categories = await _category_counts(
        db, _public_filters(query, index=index, ignore=frozenset({"category"})), index
    )
    availability = {"available": 0, "sold-out": 0, "coming-soon": 0}
    status_stmt = _apply(
        select(Product.status, func.count()).group_by(Product.status),
        _public_filters(query, index=index, ignore=frozenset({"status"})),
    )
    for status, count in (await db.execute(status_stmt)).all():
        if status in availability:
            availability[str(status)] = int(count)
    return PublicProductList(
        items=[public_card(product, index) for product in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=page_count(total, query.page_size),
        category_counts=PublicCategoryCounts(
            gadgets=categories["gadgets"],
            fashion=categories["fashion"],
        ),
        availability_counts=AvailabilityCounts(
            available=availability["available"],
            sold_out=availability["sold-out"],
            coming_soon=availability["coming-soon"],
        ),
    )


async def read_public(db: AsyncSession, product_id: uuid.UUID) -> PublicProductDetail:
    return await _public_detail(db, Product.id == product_id)


async def read_public_by_slug(db: AsyncSession, slug: str) -> PublicProductDetail:
    return await _public_detail(db, Product.slug == slug)


async def _public_detail(db: AsyncSession, match: Any) -> PublicProductDetail:
    # Missing and unpublished share one response so a hidden product is not confirmed.
    index = await category_service.load_index(db)
    result = await db.execute(select(Product).where(match, Product.published.is_(True)))
    product = result.scalar_one_or_none()
    if product is None or not index.visible(product.category_id):
        raise NotFoundError("Product not found")
    related = list(
        (
            await db.execute(
                select(Product)
                .where(
                    Product.published.is_(True),
                    Product.category_id == product.category_id,
                    Product.id != product.id,
                )
                .options(defer(Product.content))
                .order_by(Product.featured.desc(), Product.sort_order.asc(), Product.id.asc())
                .limit(_RELATED_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    variants = await variant_service.list_variants(db, product.id) if product.has_variants else []
    return public_detail(product, related, index, variants)
