import uuid

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.home.category import HomeCategory, HomeCategoryTile
from app.schemas.home.category import (
    CategoryAdmin,
    CategoryHeadingUpdate,
    CategoryPublic,
    CategoryReorder,
    CategoryTilePublic,
    CategoryTileRead,
    CategoryTileUpdate,
    CategoryTileWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

CATEGORY_SLUG = "home"
MAX_TILES = 24
_MEDIA = "categories"
DEFAULT_HEADING = "ক্যাটাগরি"
DEFAULTS: tuple[dict[str, object], ...] = (
    {
        "label": "ট্রেন্ডিং গ্যাজেট",
        "href": "/products?category=gadgets",
        "image_src": "/images/products/lamp/lamp-5.jpg",
        "sort_order": 0,
    },
    {
        "label": "গর্জিয়াস ড্রেস",
        "href": "/products?category=fashion",
        "image_src": "/images/products/baby-products/wedding-dress.jpeg",
        "sort_order": 1,
    },
)


def present(tile: HomeCategoryTile) -> CategoryTileRead:
    return CategoryTileRead.model_validate(tile)


def _reject_staged_path(src: str | None) -> None:
    if src and (src.startswith("/uploads/") or src.startswith("blob:")):
        raise UnprocessableError("Send the image file with the category")


async def _tiles(
    db: AsyncSession, category_id: uuid.UUID, *, active_only: bool
) -> list[HomeCategoryTile]:
    query = select(HomeCategoryTile).where(HomeCategoryTile.category_id == category_id)
    if active_only:
        query = query.where(HomeCategoryTile.is_active.is_(True))
    query = query.order_by(HomeCategoryTile.sort_order, HomeCategoryTile.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_categories(db: AsyncSession) -> HomeCategory:
    row = await db.scalar(select(HomeCategory).where(HomeCategory.slug == CATEGORY_SLUG))
    if row is not None:
        return row
    row = HomeCategory(slug=CATEGORY_SLUG, heading=DEFAULT_HEADING)
    db.add(row)
    await db.flush()
    for raw in DEFAULTS:
        db.add(HomeCategoryTile(category_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CategoryAdmin:
    row = await ensure_categories(db)
    tiles = await _tiles(db, row.id, active_only=False)
    return CategoryAdmin(heading=row.heading, tiles=[present(tile) for tile in tiles])


async def public_view(db: AsyncSession) -> CategoryPublic:
    row = await ensure_categories(db)
    tiles = await _tiles(db, row.id, active_only=True)
    return CategoryPublic(
        heading=row.heading,
        tiles=[
            CategoryTilePublic(
                id=tile.id, label=tile.label, href=tile.href, image_src=tile.image_src
            )
            for tile in tiles
        ],
    )


async def update_heading(
    db: AsyncSession, payload: CategoryHeadingUpdate
) -> CategoryAdmin:
    row = await ensure_categories(db)
    row.heading = payload.heading
    await db.commit()
    return await admin_view(db)


async def get_tile(db: AsyncSession, tile_id: uuid.UUID) -> HomeCategoryTile:
    tile = await db.get(HomeCategoryTile, tile_id)
    if tile is None:
        raise NotFoundError("Category not found")
    return tile


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


def _drop_image(stored: str | None) -> None:
    if stored:
        delete_owned_media({stored}, folder=_MEDIA)


async def create_tile(
    db: AsyncSession, payload: CategoryTileWrite, image: UploadFile | None = None
) -> CategoryTileRead:
    stored = await _take_image(image)
    try:
        if stored is not None:
            payload = payload.model_copy(update={"image_src": stored})
        _reject_staged_path(payload.image_src)
        row = await ensure_categories(db)
        count = await db.scalar(
            select(func.count())
            .select_from(HomeCategoryTile)
            .where(HomeCategoryTile.category_id == row.id)
        )
        if int(count or 0) >= MAX_TILES:
            raise UnprocessableError("You can show up to 24 categories")
        current = await db.scalar(
            select(func.max(HomeCategoryTile.sort_order)).where(
                HomeCategoryTile.category_id == row.id
            )
        )
        tile = HomeCategoryTile(
            category_id=row.id,
            sort_order=0 if current is None else int(current) + 1,
            **payload.model_dump(),
        )
        db.add(tile)
        await db.commit()
    except Exception:
        _drop_image(stored)
        raise
    await db.refresh(tile)
    return present(tile)


async def update_tile(
    db: AsyncSession,
    tile: HomeCategoryTile,
    payload: CategoryTileUpdate,
    image: UploadFile | None = None,
) -> CategoryTileRead:
    stored = await _take_image(image)
    previous = owned_refs(tile.image_src, folder=_MEDIA)
    try:
        if stored is not None:
            payload = payload.model_copy(update={"image_src": stored})
        _reject_staged_path(payload.image_src)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(tile, field, value)
        await db.commit()
    except Exception:
        _drop_image(stored)
        raise
    await db.refresh(tile)
    if stored is not None:
        replaced = previous - owned_refs(tile.image_src, folder=_MEDIA)
        delete_owned_media(replaced, folder=_MEDIA)
    return present(tile)


async def delete_tile(db: AsyncSession, tile: HomeCategoryTile) -> None:
    owned = owned_refs(tile.image_src, folder=_MEDIA)
    await db.delete(tile)
    await db.commit()
    delete_owned_media(owned, folder=_MEDIA)


async def reorder(db: AsyncSession, payload: CategoryReorder) -> CategoryAdmin:
    row = await ensure_categories(db)
    tiles = await _tiles(db, row.id, active_only=False)
    current = {tile.id for tile in tiles}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every category in the new order")
    order = {tile_id: index for index, tile_id in enumerate(incoming)}
    for tile in tiles:
        tile.sort_order = order[tile.id]
    await db.commit()
    return await admin_view(db)
