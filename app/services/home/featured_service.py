import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.home.featured import HomeFeatured, HomeFeaturedItem
from app.models.product import Product
from app.schemas.home.featured import (
    FeaturedAdmin,
    FeaturedCopyUpdate,
    FeaturedItemRead,
    FeaturedItemWrite,
    FeaturedProductCard,
    FeaturedPublic,
    FeaturedReorder,
)

FEATURED_SLUG = "home"
MAX_ITEMS = 12
SEED_LIMIT = 4
DEFAULT_HEADING = "ফিচার্ড প্রোডাক্ট"
DEFAULT_VIEW_ALL = "সব দেখুন"
DEFAULT_HREF = "/products?view=featured"


def _card(product: Product) -> FeaturedProductCard:
    return FeaturedProductCard(
        id=product.id,
        slug=product.slug,
        title=product.title,
        price=product.price,
        image_src=product.image_src,
        published=product.published,
    )


def _present(item: HomeFeaturedItem, product: Product | None) -> FeaturedItemRead:
    return FeaturedItemRead(
        id=item.id,
        product_id=item.product_id,
        sort_order=item.sort_order,
        product=_card(product) if product is not None else None,
    )


def _catalog_order():
    rank = case(
        (Product.badge == "Best Seller", 0),
        (Product.badge == "New", 1),
        (Product.status == "available", 2),
        else_=3,
    )
    return (rank.asc(), Product.sort_order.asc(), Product.id.asc())


async def _items(db: AsyncSession, featured_id: uuid.UUID) -> list[HomeFeaturedItem]:
    result = await db.execute(
        select(HomeFeaturedItem)
        .where(HomeFeaturedItem.featured_id == featured_id)
        .order_by(HomeFeaturedItem.sort_order, HomeFeaturedItem.created_at)
    )
    return list(result.scalars().all())


async def _products(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Product]:
    if not ids:
        return {}
    result = await db.scalars(
        select(Product).where(Product.id.in_(ids)).options(defer(Product.content))
    )
    return {product.id: product for product in result.all()}


async def _choices(db: AsyncSession) -> list[FeaturedProductCard]:
    result = await db.scalars(
        select(Product).options(defer(Product.content)).order_by(Product.title, Product.id)
    )
    return [_card(product) for product in result.all()]


async def ensure_featured(db: AsyncSession) -> HomeFeatured:
    row = await db.scalar(select(HomeFeatured).where(HomeFeatured.slug == FEATURED_SLUG))
    if row is not None:
        return row
    row = HomeFeatured(
        slug=FEATURED_SLUG,
        heading=DEFAULT_HEADING,
        view_all_label=DEFAULT_VIEW_ALL,
        view_all_href=DEFAULT_HREF,
    )
    db.add(row)
    await db.flush()
    seeded = await _seed_products(db)
    for index, product in enumerate(seeded):
        db.add(
            HomeFeaturedItem(
                featured_id=row.id,
                product_id=product.id,
                sort_order=index,
            )
        )
    await db.commit()
    await db.refresh(row)
    return row


async def _seed_products(db: AsyncSession) -> list[Product]:
    featured = await db.scalars(
        select(Product)
        .where(Product.published.is_(True), Product.featured.is_(True))
        .options(defer(Product.content))
        .order_by(*_catalog_order())
        .limit(SEED_LIMIT)
    )
    rows = list(featured.all())
    if rows:
        return rows
    fallback = await db.scalars(
        select(Product)
        .where(Product.published.is_(True))
        .options(defer(Product.content))
        .order_by(*_catalog_order())
        .limit(SEED_LIMIT)
    )
    return list(fallback.all())


async def admin_view(db: AsyncSession) -> FeaturedAdmin:
    row = await ensure_featured(db)
    items = await _items(db, row.id)
    products = await _products(db, {item.product_id for item in items})
    return FeaturedAdmin(
        heading=row.heading,
        view_all_label=row.view_all_label,
        view_all_href=row.view_all_href,
        items=[_present(item, products.get(item.product_id)) for item in items],
        choices=await _choices(db),
    )


async def public_view(db: AsyncSession) -> FeaturedPublic:
    row = await ensure_featured(db)
    items = await _items(db, row.id)
    products = await _products(db, {item.product_id for item in items})
    visible = [
        item.product_id
        for item in items
        if (product := products.get(item.product_id)) is not None and product.published
    ]
    return FeaturedPublic(
        heading=row.heading,
        view_all_label=row.view_all_label,
        view_all_href=row.view_all_href,
        product_ids=visible,
    )


async def update_copy(db: AsyncSession, payload: FeaturedCopyUpdate) -> FeaturedAdmin:
    row = await ensure_featured(db)
    row.heading = payload.heading
    row.view_all_label = payload.view_all_label
    row.view_all_href = payload.view_all_href
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> HomeFeaturedItem:
    item = await db.get(HomeFeaturedItem, item_id)
    if item is None:
        raise NotFoundError("Featured product not found")
    return item


async def _require_product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise UnprocessableError("Choose a product from the catalog")
    return product


async def _reject_duplicate(
    db: AsyncSession,
    featured_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    ignore: uuid.UUID | None = None,
) -> None:
    current = await db.scalar(
        select(HomeFeaturedItem.id).where(
            HomeFeaturedItem.featured_id == featured_id,
            HomeFeaturedItem.product_id == product_id,
        )
    )
    if current is not None and current != ignore:
        raise UnprocessableError("That product is already featured")


async def create_item(db: AsyncSession, payload: FeaturedItemWrite) -> FeaturedItemRead:
    await _require_product(db, payload.product_id)
    row = await ensure_featured(db)
    await _reject_duplicate(db, row.id, payload.product_id)
    count = await db.scalar(
        select(func.count())
        .select_from(HomeFeaturedItem)
        .where(HomeFeaturedItem.featured_id == row.id)
    )
    if int(count or 0) >= MAX_ITEMS:
        raise UnprocessableError("You can feature up to 12 products")
    current = await db.scalar(
        select(func.max(HomeFeaturedItem.sort_order)).where(
            HomeFeaturedItem.featured_id == row.id
        )
    )
    item = HomeFeaturedItem(
        featured_id=row.id,
        product_id=payload.product_id,
        sort_order=0 if current is None else int(current) + 1,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    product = await db.get(Product, item.product_id)
    return _present(item, product)


async def update_item(
    db: AsyncSession, item: HomeFeaturedItem, payload: FeaturedItemWrite
) -> FeaturedItemRead:
    await _require_product(db, payload.product_id)
    await _reject_duplicate(db, item.featured_id, payload.product_id, ignore=item.id)
    item.product_id = payload.product_id
    await db.commit()
    await db.refresh(item)
    product = await db.get(Product, item.product_id)
    return _present(item, product)


async def delete_item(db: AsyncSession, item: HomeFeaturedItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: FeaturedReorder) -> FeaturedAdmin:
    row = await ensure_featured(db)
    items = await _items(db, row.id)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every featured product in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
