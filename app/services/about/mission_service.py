import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.about.mission import AboutMissionCard, AboutMissionSection
from app.schemas.about.mission import (
    MissionCardPublic,
    MissionCardRead,
    MissionCardWrite,
    MissionPublic,
)

SECTION_SLUG = "about"
CARD_KEYS = ("vision", "mission")
DEFAULTS: tuple[dict[str, object], ...] = (
    {
        "card_key": "vision",
        "icon": "visibility",
        "title": "আমাদের ভিশন",
        "description": (
            "বাংলাদেশের সবচেয়ে বিশ্বাসযোগ্য অনলাইন শপিং ডেস্টিনেশন হয়ে ওঠা — "
            "যেখানে প্রতিটি ক্যাটাগরির প্রতিটি অর্ডার মানেই নিশ্চিন্ত, ঝুঁকিমুক্ত অভিজ্ঞতা।"
        ),
        "sort_order": 0,
    },
    {
        "card_key": "mission",
        "icon": "rocket_launch",
        "title": "আমাদের মিশন",
        "description": (
            "কোয়ালিটি চেক করা প্রোডাক্ট সহজলভ্য দামে, ক্যাশ অন ডেলিভারিতে এবং সহজ রিটার্ন "
            "সুবিধায় সারাদেশে পৌঁছে দেওয়া — আজ ট্রেন্ডিং গ্যাজেট দিয়ে শুরু, "
            "আগামীতে আরও অনেক ক্যাটাগরি।"
        ),
        "sort_order": 1,
    },
)


def present(card: AboutMissionCard) -> MissionCardRead:
    return MissionCardRead(
        id=card.id,
        key=card.card_key,  # type: ignore[arg-type]
        icon=card.icon,
        title=card.title,
        description=card.description,
        is_active=card.is_active,
    )


async def _cards(
    db: AsyncSession, section_id: uuid.UUID, *, active_only: bool
) -> list[AboutMissionCard]:
    query = select(AboutMissionCard).where(AboutMissionCard.section_id == section_id)
    if active_only:
        query = query.where(AboutMissionCard.is_active.is_(True))
    query = query.order_by(AboutMissionCard.sort_order, AboutMissionCard.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_section(db: AsyncSession) -> AboutMissionSection:
    row = await db.scalar(
        select(AboutMissionSection).where(AboutMissionSection.slug == SECTION_SLUG)
    )
    if row is not None:
        return row
    row = AboutMissionSection(slug=SECTION_SLUG)
    db.add(row)
    await db.flush()
    for raw in DEFAULTS:
        db.add(AboutMissionCard(section_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def list_cards(db: AsyncSession) -> list[MissionCardRead]:
    row = await ensure_section(db)
    return [present(card) for card in await _cards(db, row.id, active_only=False)]


async def public_cards(db: AsyncSession) -> MissionPublic:
    row = await ensure_section(db)
    cards = await _cards(db, row.id, active_only=True)
    return MissionPublic(
        items=[
            MissionCardPublic(
                id=card.id,
                key=card.card_key,  # type: ignore[arg-type]
                icon=card.icon,
                title=card.title,
                description=card.description,
            )
            for card in cards
        ]
    )


async def get_card(db: AsyncSession, card_key: str) -> AboutMissionCard:
    if card_key not in CARD_KEYS:
        raise NotFoundError("Card not found")
    row = await ensure_section(db)
    card = await db.scalar(
        select(AboutMissionCard).where(
            AboutMissionCard.section_id == row.id,
            AboutMissionCard.card_key == card_key,
        )
    )
    if card is None:
        raise NotFoundError("Card not found")
    return card


async def update_card(
    db: AsyncSession, card: AboutMissionCard, payload: MissionCardWrite
) -> MissionCardRead:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if not payload.description:
        raise UnprocessableError("Description is required.")
    card.icon = payload.icon
    card.title = payload.title
    card.description = payload.description
    card.is_active = payload.is_active
    await db.commit()
    await db.refresh(card)
    return present(card)
