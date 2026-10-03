import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.faqs.hero import FaqHero, FaqHeroSearch
from app.schemas.faqs.hero import HeroAdmin, HeroPublic, HeroWrite, SearchPublic, SearchRead

SECTION_SLUG = "faqs"
MAX_SEARCHES = 12
EMPTY = HeroPublic(
    eyebrow="",
    title="",
    subtitle="",
    placeholder="",
    search_label="",
    clear_label="",
    trending_label="",
    trending=[],
)


def _admin(row: FaqHero, searches: list[FaqHeroSearch]) -> HeroAdmin:
    return HeroAdmin(
        is_active=row.is_active,
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        placeholder=row.placeholder,
        search_label=row.search_label,
        clear_label=row.clear_label,
        trending_label=row.trending_label,
        trending=[
            SearchRead(id=str(item.id), label=item.label, is_active=item.is_active)
            for item in searches
        ],
    )


def _public(row: FaqHero, searches: list[FaqHeroSearch]) -> HeroPublic:
    if not row.is_active or not row.title:
        return EMPTY
    return HeroPublic(
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        placeholder=row.placeholder,
        search_label=row.search_label,
        clear_label=row.clear_label,
        trending_label=row.trending_label,
        trending=[
            SearchPublic(id=str(item.id), label=item.label) for item in searches if item.is_active
        ],
    )


async def _searches(db: AsyncSession, hero_id: object) -> list[FaqHeroSearch]:
    rows = await db.scalars(
        select(FaqHeroSearch)
        .where(FaqHeroSearch.hero_id == hero_id)
        .order_by(FaqHeroSearch.sort_order, FaqHeroSearch.created_at)
    )
    return list(rows)


async def ensure_hero(db: AsyncSession) -> FaqHero:
    row = await db.scalar(select(FaqHero).where(FaqHero.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = FaqHero(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> HeroAdmin:
    row = await ensure_hero(db)
    return _admin(row, await _searches(db, row.id))


async def public_view(db: AsyncSession) -> HeroPublic:
    row = await ensure_hero(db)
    return _public(row, await _searches(db, row.id))


def _check(payload: HeroWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if len(payload.trending) > MAX_SEARCHES:
        raise UnprocessableError("You can add up to 12 quick searches.")
    if any(not item.label for item in payload.trending):
        raise UnprocessableError("Every quick search needs a word.")


def _match(raw: str | None, existing: dict[uuid.UUID, FaqHeroSearch]) -> FaqHeroSearch | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


async def update_hero(db: AsyncSession, payload: HeroWrite) -> HeroAdmin:
    _check(payload)
    row = await ensure_hero(db)
    row.is_active = payload.is_active
    row.eyebrow = payload.eyebrow
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.placeholder = payload.placeholder
    row.search_label = payload.search_label
    row.clear_label = payload.clear_label
    row.trending_label = payload.trending_label
    existing = {item.id: item for item in await _searches(db, row.id)}
    for index, item in enumerate(payload.trending):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                FaqHeroSearch(
                    hero_id=row.id,
                    label=item.label,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.label = item.label
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)
    for extra in existing.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _searches(db, row.id))
