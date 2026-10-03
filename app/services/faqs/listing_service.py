from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.faqs.listing import FaqListing
from app.schemas.faqs.listing import ListingAdmin, ListingPublic, ListingWrite

SECTION_SLUG = "faqs"
EMPTY = ListingPublic(count_suffix="", empty_title="", empty_body="")


def present(row: FaqListing) -> ListingAdmin:
    return ListingAdmin(
        is_active=row.is_active,
        count_suffix=row.count_suffix,
        empty_title=row.empty_title,
        empty_body=row.empty_body,
    )


def present_public(row: FaqListing) -> ListingPublic:
    if not row.is_active:
        return EMPTY
    shown = present(row)
    return ListingPublic(
        count_suffix=shown.count_suffix,
        empty_title=shown.empty_title,
        empty_body=shown.empty_body,
    )


async def ensure_listing(db: AsyncSession) -> FaqListing:
    row = await db.scalar(select(FaqListing).where(FaqListing.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = FaqListing(slug=SECTION_SLUG, is_active=True)
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
    row.count_suffix = payload.count_suffix
    row.empty_title = payload.empty_title
    row.empty_body = payload.empty_body
    await db.commit()
    await db.refresh(row)
    return present(row)
