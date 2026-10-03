import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.home.showcase import HomeShowcase, HomeShowcaseItem, HomeShowcaseRow
from app.models.product import Product
from app.schemas.home.featured import FeaturedProductCard
from app.schemas.home.showcase import (
    ShowcaseAdmin,
    ShowcaseItemRead,
    ShowcaseItemWrite,
    ShowcasePublic,
    ShowcaseReorder,
    ShowcaseRowAdmin,
    ShowcaseRowPublic,
    ShowcaseRowUpdate,
    clean_href,
)

SHOWCASE_SLUG = "home"
MAX_ITEMS = 12
SEED_LIMIT = 4
ROW_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("gadgets", "ট্রেন্ডিং গ্যাজেট", "/products?category=gadgets"),
    ("fashion", "গর্জিয়াস ড্রেস", "/products?category=fashion"),
)


def _card(product: Product) -> FeaturedProductCard:
    return FeaturedProductCard(
        id=product.id,
        slug=product.slug,
        title=product.title,
        price=product.price,
        image_src=product.image_src,
        published=product.published,
    )


def _present(item: HomeShowcaseItem, product: Product | None) -> ShowcaseItemRead:
    return ShowcaseItemRead(
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


def _default_href(key: str) -> str:
    for row_key, _heading, href in ROW_DEFAULTS:
        if row_key == key:
            return href
    return "/products"


async def _items(db: AsyncSession, row_id: uuid.UUID) -> list[HomeShowcaseItem]:
    result = await db.execute(
        select(HomeShowcaseItem)
        .where(HomeShowcaseItem.row_id == row_id)
        .order_by(HomeShowcaseItem.sort_order, HomeShowcaseItem.created_at)
    )
    return list(result.scalars().all())


async def _rows(db: AsyncSession, showcase_id: uuid.UUID) -> list[HomeShowcaseRow]:
    result = await db.execute(
        select(HomeShowcaseRow)
        .where(HomeShowcaseRow.showcase_id == showcase_id)
        .order_by(HomeShowcaseRow.sort_order, HomeShowcaseRow.created_at)
    )
    return list(result.scalars().all())


async def _products(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Product]:
    if not ids:
        return {}
    result = await db.scalars(
        select(Product).where(Product.id.in_(ids)).options(defer(Product.content))
    )
    return {product.id: product for product in result.all()}


async def _choices(db: AsyncSession, category: str) -> list[FeaturedProductCard]:
    result = await db.scalars(
        select(Product)
        .where(Product.category == category)
        .options(defer(Product.content))
        .order_by(Product.title, Product.id)
    )
    return [_card(product) for product in result.all()]


async def ensure_showcase(db: AsyncSession) -> HomeShowcase:
    row = await db.scalar(select(HomeShowcase).where(HomeShowcase.slug == SHOWCASE_SLUG))
    if row is not None:
        return row
    row = HomeShowcase(slug=SHOWCASE_SLUG)
    db.add(row)
    await db.flush()
    for index, (key, heading, href) in enumerate(ROW_DEFAULTS):
        child = HomeShowcaseRow(
            showcase_id=row.id,
            key=key,
            heading=heading,
            href=href,
            sort_order=index,
        )
        db.add(child)
        await db.flush()
        seeded = await _seed_products(db, key)
        for position, product in enumerate(seeded):
            db.add(
                HomeShowcaseItem(
                    row_id=child.id,
                    product_id=product.id,
                    sort_order=position,
                )
            )
    await db.commit()
    await db.refresh(row)
    return row


async def _seed_products(db: AsyncSession, category: str) -> list[Product]:
    result = await db.scalars(
        select(Product)
        .where(Product.published.is_(True), Product.category == category)
        .options(defer(Product.content))
        .order_by(*_catalog_order())
        .limit(SEED_LIMIT)
    )
    return list(result.all())


async def _row_admin(
    db: AsyncSession, row: HomeShowcaseRow, products: dict[uuid.UUID, Product] | None = None
) -> ShowcaseRowAdmin:
    items = await _items(db, row.id)
    if products is None:
        products = await _products(db, {item.product_id for item in items})
    return ShowcaseRowAdmin(
        id=row.id,
        key=row.key,
        heading=row.heading,
        href=row.href,
        items=[_present(item, products.get(item.product_id)) for item in items],
        choices=await _choices(db, row.key),
    )


async def admin_view(db: AsyncSession) -> ShowcaseAdmin:
    parent = await ensure_showcase(db)
    rows = await _rows(db, parent.id)
    return ShowcaseAdmin(rows=[await _row_admin(db, row) for row in rows])


async def public_view(db: AsyncSession) -> ShowcasePublic:
    parent = await ensure_showcase(db)
    rows = await _rows(db, parent.id)
    visible: list[ShowcaseRowPublic] = []
    for row in rows:
        items = await _items(db, row.id)
        products = await _products(db, {item.product_id for item in items})
        visible.append(
            ShowcaseRowPublic(
                key=row.key,
                heading=row.heading,
                href=row.href,
                product_ids=[
                    item.product_id
                    for item in items
                    if (product := products.get(item.product_id)) is not None
                    and product.published
                ],
            )
        )
    return ShowcasePublic(rows=visible)


async def get_row(db: AsyncSession, key: str) -> HomeShowcaseRow:
    parent = await ensure_showcase(db)
    row = await db.scalar(
        select(HomeShowcaseRow).where(
            HomeShowcaseRow.showcase_id == parent.id,
            HomeShowcaseRow.key == key,
        )
    )
    if row is None:
        raise NotFoundError("Showcase row not found")
    return row


async def update_row(
    db: AsyncSession, row: HomeShowcaseRow, payload: ShowcaseRowUpdate
) -> ShowcaseAdmin:
    try:
        href = clean_href(payload.href, _default_href(row.key))
    except ValueError as exc:
        raise UnprocessableError("View all link must start with / or http") from exc
    row.heading = payload.heading
    row.href = href
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, row: HomeShowcaseRow, item_id: uuid.UUID) -> HomeShowcaseItem:
    item = await db.get(HomeShowcaseItem, item_id)
    if item is None or item.row_id != row.id:
        raise NotFoundError("Showcase product not found")
    return item


async def _require_product(
    db: AsyncSession, row: HomeShowcaseRow, product_id: uuid.UUID
) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise UnprocessableError("Choose a product from the catalog")
    if product.category != row.key:
        raise UnprocessableError("Choose a product from this category")
    return product


async def _reject_duplicate(
    db: AsyncSession,
    row_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    ignore: uuid.UUID | None = None,
) -> None:
    current = await db.scalar(
        select(HomeShowcaseItem.id).where(
            HomeShowcaseItem.row_id == row_id,
            HomeShowcaseItem.product_id == product_id,
        )
    )
    if current is not None and current != ignore:
        raise UnprocessableError("That product is already in this row")


async def create_item(
    db: AsyncSession, row: HomeShowcaseRow, payload: ShowcaseItemWrite
) -> ShowcaseItemRead:
    await _require_product(db, row, payload.product_id)
    await _reject_duplicate(db, row.id, payload.product_id)
    count = await db.scalar(
        select(func.count()).select_from(HomeShowcaseItem).where(HomeShowcaseItem.row_id == row.id)
    )
    if int(count or 0) >= MAX_ITEMS:
        raise UnprocessableError("You can show up to 12 products in this row")
    current = await db.scalar(
        select(func.max(HomeShowcaseItem.sort_order)).where(HomeShowcaseItem.row_id == row.id)
    )
    item = HomeShowcaseItem(
        row_id=row.id,
        product_id=payload.product_id,
        sort_order=0 if current is None else int(current) + 1,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    product = await db.get(Product, item.product_id)
    return _present(item, product)


async def update_item(
    db: AsyncSession, row: HomeShowcaseRow, item: HomeShowcaseItem, payload: ShowcaseItemWrite
) -> ShowcaseItemRead:
    await _require_product(db, row, payload.product_id)
    await _reject_duplicate(db, row.id, payload.product_id, ignore=item.id)
    item.product_id = payload.product_id
    await db.commit()
    await db.refresh(item)
    product = await db.get(Product, item.product_id)
    return _present(item, product)


async def delete_item(db: AsyncSession, item: HomeShowcaseItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(
    db: AsyncSession, row: HomeShowcaseRow, payload: ShowcaseReorder
) -> ShowcaseAdmin:
    items = await _items(db, row.id)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every product in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
