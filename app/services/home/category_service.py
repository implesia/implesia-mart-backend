"""Home "categories" section: heading plus a compatibility view over the real catalog tree.

Since migration 0075 the tiles are NOT stored separately any more. They are the catalog
categories (`app.services.category_service`), so the hero navigation, the dashboard, the
listing pages, and the product forms all read ONE tree. The legacy tile endpoints still
work for an older admin build: they translate to category operations (the tile `href` is
always `/products?category=<slug>` and is ignored on write). The old `home_category_tiles`
table is left in place, unused, for one release (see migration 0075).
"""

import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnprocessableError
from app.models.category import Category
from app.models.home.category import HomeCategory
from app.schemas.category import CategoryUpdate, CategoryWrite
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
from app.services import category_service

CATEGORY_SLUG = "home"
DEFAULT_HEADING = "ক্যাটাগরি"


def _href(category: Category) -> str:
    return f"/products?category={category.slug}"


def present(category: Category) -> CategoryTileRead:
    return CategoryTileRead(
        id=category.id,
        parent_id=category.parent_id,
        label=category.name,
        href=_href(category),
        image_src=category.image_src,
        is_active=category.is_active,
        sort_order=category.sort_order,
    )


async def ensure_categories(db: AsyncSession) -> HomeCategory:
    row = await db.scalar(select(HomeCategory).where(HomeCategory.slug == CATEGORY_SLUG))
    if row is not None:
        return row
    row = HomeCategory(slug=CATEGORY_SLUG, heading=DEFAULT_HEADING)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _flat(index: category_service.CategoryIndex) -> list[Category]:
    out: list[Category] = []

    def walk(parent: uuid.UUID | None) -> None:
        for row in index.kids(parent):
            out.append(row)
            walk(row.id)

    walk(None)
    return out


async def admin_view(db: AsyncSession) -> CategoryAdmin:
    row = await ensure_categories(db)
    index = await category_service.load_index(db)
    return CategoryAdmin(heading=row.heading, tiles=[present(item) for item in _flat(index)])


async def public_view(db: AsyncSession) -> CategoryPublic:
    row = await ensure_categories(db)
    index = await category_service.load_index(db)
    hidden = index.hidden_ids()
    return CategoryPublic(
        heading=row.heading,
        tiles=[
            CategoryTilePublic(
                id=item.id,
                parent_id=item.parent_id,
                label=item.name,
                href=_href(item),
                image_src=item.image_src,
            )
            for item in _flat(index)
            if item.id not in hidden
        ],
    )


async def update_heading(db: AsyncSession, payload: CategoryHeadingUpdate) -> CategoryAdmin:
    row = await ensure_categories(db)
    row.heading = payload.heading
    await db.commit()
    return await admin_view(db)


async def get_tile(db: AsyncSession, tile_id: uuid.UUID) -> Category:
    return await category_service.get(db, tile_id)


async def create_tile(
    db: AsyncSession, payload: CategoryTileWrite, image: UploadFile | None = None
) -> CategoryTileRead:
    created = await category_service.create(
        db,
        CategoryWrite(
            parent_id=payload.parent_id,
            name=payload.label,
            image_src=payload.image_src,
            is_active=payload.is_active,
        ),
        image,
    )
    return present(created)


async def update_tile(
    db: AsyncSession,
    tile: Category,
    payload: CategoryTileUpdate,
    image: UploadFile | None = None,
) -> CategoryTileRead:
    fields = payload.model_dump(exclude_unset=True)
    mapped: dict[str, object] = {}
    if "parent_id" in fields:
        mapped["parent_id"] = fields["parent_id"]
    if fields.get("label") is not None:
        mapped["name"] = fields["label"]
    if fields.get("image_src") is not None:
        mapped["image_src"] = fields["image_src"]
    if fields.get("is_active") is not None:
        mapped["is_active"] = fields["is_active"]
    updated = await category_service.update_category(
        db, tile, CategoryUpdate.model_validate(mapped), image
    )
    return present(updated)


async def delete_tile(db: AsyncSession, tile: Category) -> None:
    """Old behaviour kept: subcategories move up one level. A category with products is
    refused (409) by `category_service.delete_category`."""
    index = await category_service.load_index(db)
    for child in index.kids(tile.id):
        child.parent_id = tile.parent_id
    await db.flush()
    try:
        await category_service.delete_category(db, tile)
    except ConflictError:
        await db.rollback()
        raise


async def reorder(db: AsyncSession, payload: CategoryReorder) -> CategoryAdmin:
    index = await category_service.load_index(db)
    if len(payload.ids) != len(set(payload.ids)) or set(payload.ids) != set(index.by_id):
        raise UnprocessableError("Send every category in the new order")
    for position, category_id in enumerate(payload.ids):
        index.by_id[category_id].sort_order = position
    await db.commit()
    return await admin_view(db)
