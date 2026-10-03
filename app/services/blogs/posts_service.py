import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.blogs.categories import BlogCategoryItem
from app.models.blogs.posts import BlogPost, BlogPostBlock
from app.schemas.blogs.posts import (
    BlockAdmin,
    BlockPublic,
    BlockWrite,
    PostAdmin,
    PostPublic,
    PostReorder,
    PostsAdmin,
    PostsPublic,
    PostWrite,
    slug_ok,
)

MAX_POSTS = 50
_BLOCK_TYPES = {"paragraph", "heading", "list", "callout"}


def _sorted_blocks(post: BlogPost) -> list[BlogPostBlock]:
    return sorted(post.blocks, key=lambda block: (block.sort_order, block.created_at))


def _block_public(block: BlogPostBlock) -> BlockPublic:
    return BlockPublic(
        id=str(block.id),
        type=block.block_type,
        text=block.text,
        title=block.title,
        variant=block.variant,
        items=list(block.items or []),
    )


def _block_admin(block: BlogPostBlock) -> BlockAdmin:
    return BlockAdmin(**_block_public(block).model_dump(), is_active=block.is_active)


def _post_public(post: BlogPost) -> PostPublic:
    blocks = [_block_public(block) for block in _sorted_blocks(post) if block.is_active]
    return PostPublic(
        id=str(post.id),
        slug=post.slug,
        title=post.title,
        excerpt=post.excerpt,
        category_id=str(post.category_id) if post.category_id else None,
        cover_image=post.cover_image,
        cover_alt=post.cover_alt,
        author=post.author,
        author_role=post.author_role,
        published_at=post.published_at,
        read_time=post.read_time,
        tags=list(post.tags or []),
        related_product_slugs=list(post.related_product_slugs or []),
        blocks=blocks,
    )


def _post_admin(post: BlogPost) -> PostAdmin:
    data = _post_public(post).model_dump(exclude={"blocks"})
    return PostAdmin(
        **data,
        is_active=post.is_active,
        blocks=[_block_admin(block) for block in _sorted_blocks(post)],
    )


def _filled(block: BlockWrite) -> bool:
    if block.type == "list":
        return any(item for item in block.items)
    if block.type == "callout":
        return bool(block.title or block.text)
    return bool(block.text)


def _validate(payload: PostWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if not slug_ok(payload.slug):
        raise UnprocessableError("Slug needs lowercase English letters, numbers, and hyphens.")
    if not payload.cover_image:
        raise UnprocessableError("Cover photo is required.")
    for block in payload.blocks:
        bad_type = block.type not in _BLOCK_TYPES
        bad_variant = block.type == "callout" and block.variant not in {"tip", "note"}
        if bad_type or bad_variant or not _filled(block):
            raise UnprocessableError("Fill in every block, or remove the empty ones.")
    if any(not slug_ok(item) for item in payload.related_product_slugs):
        raise UnprocessableError("Related product links need a valid slug.")


def _apply(post: BlogPost, payload: PostWrite, category_id: uuid.UUID) -> None:
    post.slug = payload.slug
    post.is_active = payload.is_active
    post.title = payload.title
    post.excerpt = payload.excerpt
    post.category_id = category_id
    post.cover_image = payload.cover_image
    post.cover_alt = payload.cover_alt
    post.author = payload.author
    post.author_role = payload.author_role
    post.published_at = payload.published_at
    post.read_time = payload.read_time
    post.tags = list(payload.tags)
    post.related_product_slugs = list(payload.related_product_slugs)
    post.blocks.clear()
    for index, block in enumerate(payload.blocks):
        post.blocks.append(
            BlogPostBlock(
                block_type=block.type,
                text="" if block.type == "list" else block.text,
                title=block.title if block.type == "callout" else "",
                variant=block.variant if block.type == "callout" else "tip",
                items=list(block.items) if block.type == "list" else [],
                is_active=block.is_active,
                sort_order=index,
            )
        )


async def _posts(db: AsyncSession, *, active_only: bool) -> list[BlogPost]:
    stmt = (
        select(BlogPost)
        .options(selectinload(BlogPost.blocks))
        .order_by(BlogPost.sort_order, BlogPost.created_at)
    )
    if active_only:
        stmt = stmt.where(BlogPost.is_active.is_(True))
    return list(await db.scalars(stmt))


async def _category(db: AsyncSession, raw: str) -> uuid.UUID:
    try:
        key = uuid.UUID(raw)
    except ValueError:
        raise UnprocessableError("Choose a category.") from None
    row = await db.get(BlogCategoryItem, key)
    if row is None:
        raise UnprocessableError("Choose a category.")
    return key


async def _unique_slug(db: AsyncSession, slug: str, ignore: uuid.UUID | None) -> None:
    stmt = select(BlogPost.id).where(BlogPost.slug == slug)
    if ignore is not None:
        stmt = stmt.where(BlogPost.id != ignore)
    if await db.scalar(stmt) is not None:
        raise ConflictError("Another article already uses this slug.")


async def public_list(db: AsyncSession) -> PostsPublic:
    rows = await _posts(db, active_only=True)
    return PostsPublic(posts=[_post_public(row) for row in rows])


async def public_by_slug(db: AsyncSession, slug: str) -> PostPublic:
    stmt = (
        select(BlogPost)
        .options(selectinload(BlogPost.blocks))
        .where(BlogPost.slug == slug, BlogPost.is_active.is_(True))
    )
    row = await db.scalar(stmt)
    if row is None:
        raise NotFoundError("Article not found.")
    return _post_public(row)


async def admin_list(db: AsyncSession) -> PostsAdmin:
    rows = await _posts(db, active_only=False)
    return PostsAdmin(posts=[_post_admin(row) for row in rows])


async def get_post(db: AsyncSession, post_id: uuid.UUID) -> BlogPost:
    stmt = select(BlogPost).options(selectinload(BlogPost.blocks)).where(BlogPost.id == post_id)
    row = await db.scalar(stmt)
    if row is None:
        raise NotFoundError("Article not found.")
    return row


async def create_post(db: AsyncSession, payload: PostWrite) -> PostAdmin:
    _validate(payload)
    category_id = await _category(db, payload.category_id)
    await _unique_slug(db, payload.slug, None)
    total = await db.scalar(select(func.count()).select_from(BlogPost))
    if (total or 0) >= MAX_POSTS:
        raise UnprocessableError("You can add up to 50 articles.")
    current = await db.scalar(select(func.max(BlogPost.sort_order)))
    post = BlogPost(sort_order=0 if current is None else current + 1)
    _apply(post, payload, category_id)
    db.add(post)
    await db.commit()
    return _post_admin(await get_post(db, post.id))


async def update_post(db: AsyncSession, post: BlogPost, payload: PostWrite) -> PostAdmin:
    _validate(payload)
    category_id = await _category(db, payload.category_id)
    await _unique_slug(db, payload.slug, post.id)
    _apply(post, payload, category_id)
    await db.commit()
    return _post_admin(await get_post(db, post.id))


async def delete_post(db: AsyncSession, post: BlogPost) -> None:
    await db.delete(post)
    await db.commit()


async def reorder(db: AsyncSession, payload: PostReorder) -> PostsAdmin:
    rows = await _posts(db, active_only=False)
    by_id = {row.id: row for row in rows}
    if set(payload.ids) != set(by_id):
        raise UnprocessableError("Include every article when reordering.")
    for index, post_id in enumerate(payload.ids):
        by_id[post_id].sort_order = index
    await db.commit()
    return await admin_list(db)
