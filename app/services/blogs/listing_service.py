from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blogs.listing import BlogListing
from app.schemas.blogs.listing import ListingAdmin, ListingPublic, ListingWrite

SECTION_SLUG = "blogs"
EMPTY = ListingPublic(
    heading="",
    all_label="",
    count_suffix="",
    empty_message="",
    featured_label="",
    read_label="",
    read_suffix="",
    tabs_label="",
)


def present(row: BlogListing) -> ListingAdmin:
    return ListingAdmin(
        is_active=row.is_active,
        heading=row.heading,
        all_label=row.all_label,
        count_suffix=row.count_suffix,
        empty_message=row.empty_message,
        featured_label=row.featured_label,
        read_label=row.read_label,
        read_suffix=row.read_suffix,
        tabs_label=row.tabs_label,
    )


def present_public(row: BlogListing) -> ListingPublic:
    if not row.is_active:
        return EMPTY
    shown = present(row)
    return ListingPublic(
        heading=shown.heading,
        all_label=shown.all_label,
        count_suffix=shown.count_suffix,
        empty_message=shown.empty_message,
        featured_label=shown.featured_label,
        read_label=shown.read_label,
        read_suffix=shown.read_suffix,
        tabs_label=shown.tabs_label,
    )


async def ensure_listing(db: AsyncSession) -> BlogListing:
    row = await db.scalar(select(BlogListing).where(BlogListing.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = BlogListing(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> ListingAdmin:
    return present(await ensure_listing(db))


async def public_view(db: AsyncSession) -> ListingPublic:
    return present_public(await ensure_listing(db))


async def update_listing(db: AsyncSession, payload: ListingWrite) -> ListingAdmin:
    row = await ensure_listing(db)
    row.is_active = payload.is_active
    row.heading = payload.heading
    row.all_label = payload.all_label
    row.count_suffix = payload.count_suffix
    row.empty_message = payload.empty_message
    row.featured_label = payload.featured_label
    row.read_label = payload.read_label
    row.read_suffix = payload.read_suffix
    row.tabs_label = payload.tabs_label
    await db.commit()
    await db.refresh(row)
    return present(row)
