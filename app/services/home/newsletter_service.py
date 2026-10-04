import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.home.newsletter import HomeNewsletter, HomeNewsletterPerk
from app.schemas.home.newsletter import (
    NewsletterAdmin,
    NewsletterCopyUpdate,
    NewsletterPerkPublic,
    NewsletterPerkRead,
    NewsletterPerkUpdate,
    NewsletterPerkWrite,
    NewsletterPublic,
    NewsletterReorder,
)

NEWSLETTER_SLUG = "home"
MAX_PERKS = 12
DEFAULT_EYEBROW = "অফার ও আপডেট"
DEFAULT_TITLE = "নতুন অফার মিস করবেন না"
DEFAULT_SUBTITLE = "ইমেইলে পান ফ্ল্যাশ সেল, নতুন গ্যাজেট লঞ্চ আর বিশেষ ছাড়ের খবর।"
DEFAULT_PLACEHOLDER = "আপনার ইমেইল লিখুন"
DEFAULT_CTA = "সাবস্ক্রাইব"
DEFAULT_SUCCESS = "ধন্যবাদ! শীঘ্রই আপডেট পাবেন।"
DEFAULTS: tuple[dict[str, object], ...] = (
    {"icon": "local_offer", "label": "ফ্ল্যাশ অফার আপডেট", "sort_order": 0},
    {"icon": "campaign", "label": "নতুন গ্যাজেট আগে জানুন", "sort_order": 1},
    {"icon": "shield", "label": "স্প্যাম নেই", "sort_order": 2},
)


def present(perk: HomeNewsletterPerk) -> NewsletterPerkRead:
    return NewsletterPerkRead.model_validate(perk)


def _section(row: HomeNewsletter, perks: list[HomeNewsletterPerk]) -> NewsletterAdmin:
    return NewsletterAdmin(
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        placeholder=row.placeholder,
        cta=row.cta,
        success=row.success,
        perks=[present(perk) for perk in perks],
    )


async def _perks(
    db: AsyncSession, newsletter_id: uuid.UUID, *, active_only: bool
) -> list[HomeNewsletterPerk]:
    query = select(HomeNewsletterPerk).where(HomeNewsletterPerk.newsletter_id == newsletter_id)
    if active_only:
        query = query.where(HomeNewsletterPerk.is_active.is_(True))
    query = query.order_by(HomeNewsletterPerk.sort_order, HomeNewsletterPerk.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_newsletter(db: AsyncSession) -> HomeNewsletter:
    row = await db.scalar(select(HomeNewsletter).where(HomeNewsletter.slug == NEWSLETTER_SLUG))
    if row is not None:
        return row
    row = HomeNewsletter(
        slug=NEWSLETTER_SLUG,
        eyebrow=DEFAULT_EYEBROW,
        title=DEFAULT_TITLE,
        subtitle=DEFAULT_SUBTITLE,
        placeholder=DEFAULT_PLACEHOLDER,
        cta=DEFAULT_CTA,
        success=DEFAULT_SUCCESS,
    )
    db.add(row)
    await db.flush()
    for raw in DEFAULTS:
        db.add(HomeNewsletterPerk(newsletter_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> NewsletterAdmin:
    row = await ensure_newsletter(db)
    return _section(row, await _perks(db, row.id, active_only=False))


async def public_view(db: AsyncSession) -> NewsletterPublic:
    row = await ensure_newsletter(db)
    perks = await _perks(db, row.id, active_only=True)
    return NewsletterPublic(
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        placeholder=row.placeholder,
        cta=row.cta,
        success=row.success,
        perks=[
            NewsletterPerkPublic(
                id=perk.id,
                icon=perk.icon,
                label=perk.label,
            )
            for perk in perks
        ],
    )


async def update_copy(db: AsyncSession, payload: NewsletterCopyUpdate) -> NewsletterAdmin:
    row = await ensure_newsletter(db)
    row.eyebrow = payload.eyebrow
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.placeholder = payload.placeholder
    row.cta = payload.cta
    row.success = payload.success
    await db.commit()
    return await admin_view(db)


async def get_perk(db: AsyncSession, perk_id: uuid.UUID) -> HomeNewsletterPerk:
    perk = await db.get(HomeNewsletterPerk, perk_id)
    if perk is None:
        raise NotFoundError("Perk not found")
    return perk


async def create_perk(db: AsyncSession, payload: NewsletterPerkWrite) -> NewsletterPerkRead:
    row = await ensure_newsletter(db)
    count = await db.scalar(
        select(func.count())
        .select_from(HomeNewsletterPerk)
        .where(HomeNewsletterPerk.newsletter_id == row.id)
    )
    if int(count or 0) >= MAX_PERKS:
        raise UnprocessableError("You can show up to 12 perks")
    current = await db.scalar(
        select(func.max(HomeNewsletterPerk.sort_order)).where(
            HomeNewsletterPerk.newsletter_id == row.id
        )
    )
    perk = HomeNewsletterPerk(
        newsletter_id=row.id,
        sort_order=0 if current is None else int(current) + 1,
        **payload.model_dump(),
    )
    db.add(perk)
    await db.commit()
    await db.refresh(perk)
    return present(perk)


async def update_perk(
    db: AsyncSession, perk: HomeNewsletterPerk, payload: NewsletterPerkUpdate
) -> NewsletterPerkRead:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(perk, field, value)
    await db.commit()
    await db.refresh(perk)
    return present(perk)


async def delete_perk(db: AsyncSession, perk: HomeNewsletterPerk) -> None:
    await db.delete(perk)
    await db.commit()


async def reorder(db: AsyncSession, payload: NewsletterReorder) -> NewsletterAdmin:
    row = await ensure_newsletter(db)
    perks = await _perks(db, row.id, active_only=False)
    current = {perk.id for perk in perks}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every perk in the new order")
    order = {perk_id: index for index, perk_id in enumerate(incoming)}
    for perk in perks:
        perk.sort_order = order[perk.id]
    await db.commit()
    return await admin_view(db)
