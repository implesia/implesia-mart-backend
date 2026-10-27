"""Catalog category tree: reads, validation, and the safe write operations.

Storage is an adjacency list (`parent_id`). The tree is small (hundreds of rows), so every
operation loads all rows with ONE query and walks them in memory; no recursive SQL is
needed and the same code runs on PostgreSQL and the SQLite unit tests. PostgreSQL also
enforces "no cycles" with a trigger (migration 0075) as a second line of defence.

Visibility policy (single source of truth, `CategoryIndex.hidden_ids`):
  * an inactive category is hidden together with its WHOLE subtree;
  * the products inside a hidden category are hidden from every category listing and
    count, and from the public catalog (they stay in the admin);
  * a hidden category answers 404 on the public API.
"""

import re
import uuid
from collections.abc import Iterable, Sequence

from fastapi import UploadFile
from slugify import slugify
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.category import LEGACY_SLUGS, MAX_DEPTH, Category
from app.models.product import Product
from app.schemas.category import (
    RESERVED_SLUGS,
    CategoryAdminList,
    CategoryAdminRead,
    CategoryDetail,
    CategoryNode,
    CategoryOrder,
    CategoryRef,
    CategoryTree,
    CategoryUpdate,
    CategoryWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

_MEDIA = "categories"
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_CATEGORIES = 1000
LEGACY_DEFAULTS: dict[str, str] = {"gadgets": "ট্রেন্ডিং গ্যাজেট", "fashion": "গর্জিয়াস ড্রেস"}


def _sort_key(row: Category) -> tuple[int, str, str]:
    return (row.sort_order, row.name.lower(), str(row.id))


class CategoryIndex:
    """In-memory view of every category: parents, children, paths, visibility."""

    def __init__(self, rows: Sequence[Category]) -> None:
        self.rows = list(rows)
        self.by_id: dict[uuid.UUID, Category] = {row.id: row for row in self.rows}
        self.by_slug: dict[str, Category] = {row.slug: row for row in self.rows}
        self.children: dict[uuid.UUID | None, list[Category]] = {}
        for row in sorted(self.rows, key=_sort_key):
            parent = row.parent_id if row.parent_id in self.by_id else None
            self.children.setdefault(parent, []).append(row)
        self._hidden: set[uuid.UUID] | None = None

    def roots(self) -> list[Category]:
        return self.children.get(None, [])

    def kids(self, category_id: uuid.UUID | None) -> list[Category]:
        return self.children.get(category_id, [])

    def path(self, category_id: uuid.UUID) -> list[Category]:
        """Root-first chain ending at the category. Bounded, so a corrupt cycle cannot hang."""
        chain: list[Category] = []
        seen: set[uuid.UUID] = set()
        current = self.by_id.get(category_id)
        while current is not None and current.id not in seen and len(chain) <= MAX_DEPTH * 2:
            seen.add(current.id)
            chain.append(current)
            current = self.by_id.get(current.parent_id) if current.parent_id else None
        chain.reverse()
        return chain

    def depth(self, category_id: uuid.UUID) -> int:
        return len(self.path(category_id))

    def root_of(self, category_id: uuid.UUID) -> Category | None:
        chain = self.path(category_id)
        return chain[0] if chain else None

    def descendants(self, category_id: uuid.UUID, *, include_self: bool = True) -> list[uuid.UUID]:
        out: list[uuid.UUID] = [category_id] if include_self else []
        seen = {category_id}
        stack = [category_id]
        while stack:
            for child in self.kids(stack.pop()):
                if child.id not in seen:
                    seen.add(child.id)
                    out.append(child.id)
                    stack.append(child.id)
        return out

    def height(self, category_id: uuid.UUID) -> int:
        """Number of levels in the subtree, counting the category itself."""
        best = 0
        stack = [(category_id, 1)]
        seen: set[uuid.UUID] = set()
        while stack:
            current, level = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            best = max(best, level)
            stack.extend((child.id, level + 1) for child in self.kids(current))
        return best

    def hidden_ids(self) -> set[uuid.UUID]:
        if self._hidden is None:
            hidden: set[uuid.UUID] = set()
            for row in self.rows:
                if not any(not node.is_active for node in self.path(row.id)):
                    continue
                hidden.add(row.id)
            self._hidden = hidden
        return self._hidden

    def visible(self, category_id: uuid.UUID) -> bool:
        return category_id in self.by_id and category_id not in self.hidden_ids()

    def ref(self, row: Category) -> CategoryRef:
        return CategoryRef(id=row.id, slug=row.slug, name=row.name)


async def load_index(db: AsyncSession) -> CategoryIndex:
    result = await db.execute(select(Category))
    return CategoryIndex(result.scalars().all())


async def ensure_legacy(db: AsyncSession, slug: str) -> Category:
    """The `gadgets` / `fashion` roots. Created on demand on a database without them
    (a fresh install, the test database) so the legacy `category` parameter keeps working."""
    row = await db.scalar(select(Category).where(Category.slug == slug))
    if row is not None:
        return row
    if slug not in LEGACY_DEFAULTS:
        raise NotFoundError("Category not found")
    count = await db.scalar(
        select(func.count()).select_from(Category).where(Category.parent_id.is_(None))
    )
    row = Category(slug=slug, name=LEGACY_DEFAULTS[slug], sort_order=int(count or 0))
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        found = await db.scalar(select(Category).where(Category.slug == slug))
        if found is None:
            raise
        return found
    await db.refresh(row)
    return row


# --------------------------------------------------------------------------- counts


async def _direct_counts(db: AsyncSession, *, published_only: bool) -> dict[uuid.UUID, int]:
    stmt = select(Product.category_id, func.count()).group_by(Product.category_id)
    if published_only:
        stmt = stmt.where(Product.published.is_(True))
    return {cid: int(total) for cid, total in (await db.execute(stmt)).all()}


def rollup(index: CategoryIndex, direct: dict[uuid.UUID, int]) -> dict[uuid.UUID, int]:
    totals: dict[uuid.UUID, int] = {}

    def total(category_id: uuid.UUID) -> int:
        if category_id not in totals:
            totals[category_id] = 0  # cycle guard
            totals[category_id] = direct.get(category_id, 0) + sum(
                total(child.id) for child in index.kids(category_id)
            )
        return totals[category_id]

    for row in index.rows:
        total(row.id)
    return totals


# --------------------------------------------------------------------------- public


def _node(
    index: CategoryIndex, row: Category, counts: dict[uuid.UUID, int], depth: int
) -> CategoryNode:
    return CategoryNode(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        image_src=row.image_src,
        depth=depth,
        product_count=counts.get(row.id, 0),
        children=[
            _node(index, child, counts, depth + 1)
            for child in index.kids(row.id)
            if child.is_active
        ],
    )


async def public_tree(db: AsyncSession) -> CategoryTree:
    index = await load_index(db)
    counts = rollup(index, await _direct_counts(db, published_only=True))
    return CategoryTree(
        items=[_node(index, row, counts, 1) for row in index.roots() if row.is_active]
    )


async def public_detail(db: AsyncSession, slug: str) -> CategoryDetail:
    index = await load_index(db)
    row = index.by_slug.get(slug)
    if row is None or not index.visible(row.id):
        raise NotFoundError("Category not found")
    counts = rollup(index, await _direct_counts(db, published_only=True))
    chain = index.path(row.id)
    return CategoryDetail(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        image_src=row.image_src,
        meta_title=row.meta_title,
        meta_description=row.meta_description,
        depth=len(chain),
        product_count=counts.get(row.id, 0),
        path=[index.ref(item) for item in chain],
        children=[
            _node(index, child, counts, len(chain) + 1)
            for child in index.kids(row.id)
            if child.is_active
        ],
    )


def listing_scope(
    index: CategoryIndex, *, slug: str | None, category_id: uuid.UUID | None, descendants: bool
) -> list[uuid.UUID] | None:
    """Category ids a product listing is limited to (None = no category filter).

    An unknown or hidden category yields an empty list (no products), never an error, so a
    stale link shows an empty catalog instead of leaking hidden products.
    """
    row: Category | None = None
    if category_id is not None:
        row = index.by_id.get(category_id)
    elif slug is not None:
        row = index.by_slug.get(slug)
    else:
        return None
    if row is None or not index.visible(row.id):
        return []
    ids = index.descendants(row.id) if descendants else [row.id]
    hidden = index.hidden_ids()
    return [item for item in ids if item not in hidden]


# --------------------------------------------------------------------------- admin


async def admin_list(db: AsyncSession) -> CategoryAdminList:
    index = await load_index(db)
    direct = await _direct_counts(db, published_only=False)
    totals = rollup(index, direct)
    hidden = index.hidden_ids()
    items: list[CategoryAdminRead] = []

    def walk(parent: uuid.UUID | None) -> None:
        for row in index.kids(parent):
            chain = index.path(row.id)
            item = CategoryAdminRead.model_validate(row)
            item.depth = len(chain)
            item.child_count = len(index.kids(row.id))
            item.product_count = direct.get(row.id, 0)
            item.subtree_product_count = totals.get(row.id, 0)
            item.visible = row.id not in hidden
            item.path = [index.ref(node) for node in chain]
            items.append(item)
            walk(row.id)

    walk(None)
    return CategoryAdminList(items=items, max_depth=MAX_DEPTH)


async def admin_read(db: AsyncSession, category_id: uuid.UUID) -> CategoryAdminRead:
    listing = await admin_list(db)
    for item in listing.items:
        if item.id == category_id:
            return item
    raise NotFoundError("Category not found")


async def get(db: AsyncSession, category_id: uuid.UUID) -> Category:
    row = await db.get(Category, category_id)
    if row is None:
        raise NotFoundError("Category not found")
    return row


async def allocate_slug(db: AsyncSession, name: str) -> str:
    raw = re.sub(r"-{2,}", "-", slugify(name, max_length=70, lowercase=True)).strip("-")
    base = raw if _SLUG.fullmatch(raw) and raw not in RESERVED_SLUGS else "category"
    candidate = base
    for number in range(2, 100):
        taken = await db.scalar(select(Category.id).where(Category.slug == candidate).limit(1))
        if taken is None:
            return candidate
        suffix = f"-{number}"
        candidate = f"{base[: 80 - len(suffix)]}{suffix}".strip("-")
    return f"category-{uuid.uuid4().hex[:10]}"


def _check_parent(
    index: CategoryIndex, parent_id: uuid.UUID | None, *, moving: Category | None
) -> None:
    """Reject a missing parent, the node itself, a descendant, or a tree that gets too deep."""
    if parent_id is None:
        return
    parent = index.by_id.get(parent_id)
    if parent is None:
        raise UnprocessableError("Parent category not found")
    if moving is not None:
        if parent_id == moving.id:
            raise UnprocessableError("A category cannot be its own parent")
        if parent_id in index.descendants(moving.id):
            raise UnprocessableError("A category cannot move under its own subcategory")
    levels = index.depth(parent_id) + (index.height(moving.id) if moving is not None else 1)
    if levels > MAX_DEPTH:
        raise UnprocessableError(f"Categories can be nested at most {MAX_DEPTH} levels deep")


def _check_sibling_name(
    index: CategoryIndex, parent_id: uuid.UUID | None, name: str, *, own_id: uuid.UUID | None
) -> None:
    wanted = name.casefold()
    for sibling in index.kids(parent_id if parent_id in index.by_id else None):
        if sibling.id != own_id and sibling.name.casefold() == wanted:
            raise ConflictError(f"A category named “{name}” already exists here")


def _next_order(index: CategoryIndex, parent_id: uuid.UUID | None) -> int:
    siblings = index.kids(parent_id)
    return max((row.sort_order for row in siblings), default=-1) + 1


def _reject_staged_path(src: str | None) -> None:
    if src and (src.startswith("/uploads/") or src.startswith("blob:")):
        raise UnprocessableError("Send the image file with the category")


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


def _drop_image(stored: str | None) -> None:
    if stored:
        delete_owned_media({stored}, folder=_MEDIA)


def _slug_conflict(exc: IntegrityError) -> ConflictError:
    text = str(exc.orig).lower()
    if "cycle" in text:
        return ConflictError("That move would create a loop in the category tree")
    return ConflictError("A category with this slug already exists")


async def create(
    db: AsyncSession, payload: CategoryWrite, image: UploadFile | None = None
) -> Category:
    stored = await _take_image(image)
    try:
        data = payload.model_copy(update={"image_src": stored}) if stored else payload
        _reject_staged_path(data.image_src)
        index = await load_index(db)
        if len(index.rows) >= MAX_CATEGORIES:
            raise UnprocessableError(f"You can add up to {MAX_CATEGORIES} categories")
        _check_parent(index, data.parent_id, moving=None)
        _check_sibling_name(index, data.parent_id, data.name, own_id=None)
        if data.slug:
            if data.slug in index.by_slug:
                raise ConflictError("A category with this slug already exists")
            slug = data.slug
        else:
            slug = await allocate_slug(db, data.name)
        row = Category(
            parent_id=data.parent_id,
            slug=slug,
            name=data.name,
            description=data.description,
            image_src=data.image_src,
            is_active=data.is_active,
            sort_order=_next_order(index, data.parent_id),
            meta_title=data.meta_title,
            meta_description=data.meta_description,
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise _slug_conflict(exc) from exc
    except Exception:
        _drop_image(stored)
        raise
    await db.refresh(row)
    return row


async def update_category(
    db: AsyncSession, row: Category, payload: CategoryUpdate, image: UploadFile | None = None
) -> Category:
    stored = await _take_image(image)
    previous = owned_refs(row.image_src, folder=_MEDIA)
    try:
        data = payload.model_copy(update={"image_src": stored}) if stored else payload
        _reject_staged_path(data.image_src)
        changes = data.model_dump(exclude_unset=True)
        if stored:
            changes["image_src"] = stored
        index = await load_index(db)
        parent_id = row.parent_id
        if "parent_id" in changes and changes["parent_id"] != row.parent_id:
            _check_parent(index, changes["parent_id"], moving=row)
            parent_id = changes["parent_id"]
            row.sort_order = _next_order(index, parent_id)
        elif "parent_id" in changes:
            changes.pop("parent_id")
        name = changes.get("name", row.name)
        if "name" in changes or parent_id != row.parent_id:
            _check_sibling_name(index, parent_id, name, own_id=row.id)
        slug = changes.get("slug")
        if slug is not None and slug != row.slug:
            other = index.by_slug.get(slug)
            if other is not None and other.id != row.id:
                raise ConflictError("A category with this slug already exists")
        for field, value in changes.items():
            if value is None and field != "parent_id":
                continue
            setattr(row, field, value)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise _slug_conflict(exc) from exc
    except Exception:
        _drop_image(stored)
        raise
    await db.refresh(row)
    if stored is not None:
        delete_owned_media(previous - owned_refs(row.image_src, folder=_MEDIA), folder=_MEDIA)
    return row


async def reorder(db: AsyncSession, payload: CategoryOrder) -> None:
    index = await load_index(db)
    if payload.parent_id is not None and payload.parent_id not in index.by_id:
        raise UnprocessableError("Parent category not found")
    current = {row.id for row in index.kids(payload.parent_id)}
    if len(payload.ids) != len(set(payload.ids)) or set(payload.ids) != current:
        raise UnprocessableError("Send every category of this level in the new order")
    for position, category_id in enumerate(payload.ids):
        index.by_id[category_id].sort_order = position
    await db.commit()


async def usage(db: AsyncSession, category_id: uuid.UUID) -> tuple[int, int]:
    """(subcategories, products directly assigned) of one category."""
    children = await db.scalar(
        select(func.count()).select_from(Category).where(Category.parent_id == category_id)
    )
    products = await db.scalar(
        select(func.count()).select_from(Product).where(Product.category_id == category_id)
    )
    return int(children or 0), int(products or 0)


def _count_text(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


async def delete_category(
    db: AsyncSession, row: Category, *, reassign_to: uuid.UUID | None = None
) -> None:
    """Delete a category.

    A category that still has subcategories or products is refused (409) unless
    `reassign_to` names a destination: its subcategories are moved under it and its
    products are assigned to it, in the same transaction. The destination cannot be the
    category itself or inside its subtree, and the moved subtrees must still fit the depth
    limit.
    """
    children, products = await usage(db, row.id)
    owned = owned_refs(row.image_src, folder=_MEDIA)
    if (children or products) and reassign_to is None:
        parts = [
            text
            for text in (
                _count_text(children, "subcategory", "subcategories") if children else "",
                _count_text(products, "product", "products") if products else "",
            )
            if text
        ]
        raise ConflictError(
            f"“{row.name}” still has {' and '.join(parts)}. "
            "Choose a category to move them to, or move them first."
        )
    if reassign_to is not None and (children or products):
        index = await load_index(db)
        if reassign_to == row.id or reassign_to in index.descendants(row.id):
            raise UnprocessableError("Choose a destination outside the category being deleted")
        target = index.by_id.get(reassign_to)
        if target is None:
            raise UnprocessableError("Destination category not found")
        room = MAX_DEPTH - index.depth(target.id)
        for child in index.kids(row.id):
            if index.height(child.id) > room:
                raise UnprocessableError(
                    f"Moving these subcategories would exceed {MAX_DEPTH} levels"
                )
        start = _next_order(index, target.id)
        for offset, child in enumerate(index.kids(row.id)):
            await db.execute(
                update(Category)
                .where(Category.id == child.id)
                .values(parent_id=target.id, sort_order=start + offset)
            )
        await db.execute(
            update(Product).where(Product.category_id == row.id).values(category_id=target.id)
        )
        await db.flush()
    try:
        await db.delete(row)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "This category just received products or subcategories. Reload and try again."
        ) from exc
    delete_owned_media(owned, folder=_MEDIA)


# --------------------------------------------------------------------------- products


async def resolve_for_product(
    db: AsyncSession, *, category_id: uuid.UUID | None, legacy_slug: str | None
) -> Category:
    """The category a product is assigned to, from an id or the legacy `category` slug."""
    if category_id is not None:
        row = await db.get(Category, category_id)
        if row is None:
            raise UnprocessableError("Category not found")
        return row
    if legacy_slug is None:
        raise UnprocessableError("Choose a category")
    if legacy_slug in LEGACY_SLUGS:
        return await ensure_legacy(db, legacy_slug)
    row = await db.scalar(select(Category).where(Category.slug == legacy_slug))
    if row is None:
        raise UnprocessableError("Category not found")
    return row


def refs(index: CategoryIndex, category_id: uuid.UUID) -> list[CategoryRef]:
    return [index.ref(row) for row in index.path(category_id)]


def slugs(rows: Iterable[Category]) -> list[str]:
    return [row.slug for row in rows]
