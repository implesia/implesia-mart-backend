from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blogs.related import BlogRelated
from app.schemas.blogs.related import RelatedAdmin, RelatedPublic, RelatedWrite

SECTION_SLUG = "blogs"
EMPTY = RelatedPublic(
    toc_title="",
    products_title="",
    products_subtitle="",
    posts_title="",
    posts_subtitle="",
    posts_link_label="",
    coming_soon_label="",
    view_label="",
    details_label="",
)


def present(row: BlogRelated) -> RelatedAdmin:
    return RelatedAdmin(
        is_active=row.is_active,
        toc_title=row.toc_title,
        products_title=row.products_title,
        products_subtitle=row.products_subtitle,
        posts_title=row.posts_title,
        posts_subtitle=row.posts_subtitle,
        posts_link_label=row.posts_link_label,
        coming_soon_label=row.coming_soon_label,
        view_label=row.view_label,
        details_label=row.details_label,
    )


def present_public(row: BlogRelated) -> RelatedPublic:
    if not row.is_active:
        return EMPTY
    shown = present(row)
    return RelatedPublic(
        toc_title=shown.toc_title,
        products_title=shown.products_title,
        products_subtitle=shown.products_subtitle,
        posts_title=shown.posts_title,
        posts_subtitle=shown.posts_subtitle,
        posts_link_label=shown.posts_link_label,
        coming_soon_label=shown.coming_soon_label,
        view_label=shown.view_label,
        details_label=shown.details_label,
    )


async def ensure_related(db: AsyncSession) -> BlogRelated:
    row = await db.scalar(select(BlogRelated).where(BlogRelated.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = BlogRelated(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> RelatedAdmin:
    return present(await ensure_related(db))


async def public_view(db: AsyncSession) -> RelatedPublic:
    return present_public(await ensure_related(db))


async def update_related(db: AsyncSession, payload: RelatedWrite) -> RelatedAdmin:
    row = await ensure_related(db)
    row.is_active = payload.is_active
    row.toc_title = payload.toc_title
    row.products_title = payload.products_title
    row.products_subtitle = payload.products_subtitle
    row.posts_title = payload.posts_title
    row.posts_subtitle = payload.posts_subtitle
    row.posts_link_label = payload.posts_link_label
    row.coming_soon_label = payload.coming_soon_label
    row.view_label = payload.view_label
    row.details_label = payload.details_label
    await db.commit()
    await db.refresh(row)
    return present(row)
