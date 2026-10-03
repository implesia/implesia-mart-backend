import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.home.banner import BannerAccent, HomeBanner, HomeBannerSlide
from app.schemas.home.banner import (
    BannerCta,
    BannerSlideAdmin,
    BannerSlidePublic,
    BannerSlideUpdate,
    BannerSlideWrite,
    HomeBannerPublic,
    HomeBannerUpdate,
)
from app.services.home.banner_defaults import BANNER_DEFAULTS, BANNER_SLUG, SLIDE_DEFAULTS


def format_bdt(amount: int) -> str:
    return f"৳{amount:,}"


def discount_label(price: int, compare_at: int | None) -> str | None:
    if compare_at is None or compare_at <= price:
        return None
    percent = round((compare_at - price) / compare_at * 100)
    return f"{percent}% ছাড়"


def price_label(price: int, prefix: str | None) -> str:
    amount = format_bdt(price)
    if prefix:
        return f"{prefix} {amount}"
    return amount


def present_public_slide(
    slide: HomeBannerSlide, *, image_priority: bool = False
) -> BannerSlidePublic:
    shared = {
        "id": slide.id,
        "slug": slide.slug,
        "eyebrow": slide.eyebrow,
        "title": slide.title,
        "description": slide.description,
        "price": slide.price,
        "compare_at_price": slide.compare_at_price,
        "price_prefix": slide.price_prefix,
        "price_label": price_label(slide.price, slide.price_prefix),
        "compare_at_label": format_bdt(slide.compare_at_price) if slide.compare_at_price else None,
        "discount_label": discount_label(slide.price, slide.compare_at_price),
        "primary_cta": BannerCta(label=slide.primary_cta_label, href=slide.primary_cta_href),
        "secondary_cta": BannerCta(label=slide.secondary_cta_label, href=slide.secondary_cta_href),
        "image_src": slide.image_src,
        "image_alt": slide.image_alt,
        "image_priority": image_priority,
        "accent": slide.accent,
    }
    return BannerSlidePublic(**shared)


def present_admin_slide(
    slide: HomeBannerSlide, *, image_priority: bool = False
) -> BannerSlideAdmin:
    public = present_public_slide(slide, image_priority=image_priority)
    return BannerSlideAdmin(
        **public.model_dump(),
        sort_order=slide.sort_order,
        is_published=slide.is_published,
        internal_notes=slide.internal_notes,
        created_at=slide.created_at,
        updated_at=slide.updated_at,
    )


def present_public(banner: HomeBanner, slides: list[HomeBannerSlide]) -> HomeBannerPublic:
    return HomeBannerPublic(
        brand_name=banner.brand_name,
        aria_label=banner.aria_label,
        trust_line=banner.trust_line,
        previous_label=banner.previous_label,
        next_label=banner.next_label,
        slide_label=banner.slide_label,
        autoplay_delay_ms=banner.autoplay_delay_ms,
        transition_speed_ms=banner.transition_speed_ms,
        pause_on_hover=banner.pause_on_hover,
        loop=banner.loop,
        keyboard_enabled=banner.keyboard_enabled,
        disable_on_interaction=banner.disable_on_interaction,
        cross_fade=banner.cross_fade,
        slides=[
            present_public_slide(slide, image_priority=index == 0)
            for index, slide in enumerate(slides)
        ],
    )


async def _slides(
    db: AsyncSession, banner_id: uuid.UUID, *, published_only: bool
) -> list[HomeBannerSlide]:
    query = select(HomeBannerSlide).where(HomeBannerSlide.banner_id == banner_id)
    if published_only:
        query = query.where(HomeBannerSlide.is_published.is_(True))
    query = query.order_by(HomeBannerSlide.sort_order, HomeBannerSlide.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_banner(db: AsyncSession) -> HomeBanner:
    banner = await db.scalar(select(HomeBanner).where(HomeBanner.slug == BANNER_SLUG))
    if banner is not None:
        return banner

    banner = HomeBanner(**BANNER_DEFAULTS)
    db.add(banner)
    await db.flush()
    for raw in SLIDE_DEFAULTS:
        db.add(
            HomeBannerSlide(
                banner_id=banner.id,
                accent=BannerAccent(str(raw["accent"])),
                **{key: value for key, value in raw.items() if key != "accent"},
            )
        )
    await db.commit()
    await db.refresh(banner)
    return banner


async def public_banner(db: AsyncSession) -> HomeBannerPublic:
    banner = await ensure_banner(db)
    slides = await _slides(db, banner.id, published_only=True)
    return present_public(banner, slides)


async def update_banner(
    db: AsyncSession, banner: HomeBanner, payload: HomeBannerUpdate
) -> HomeBanner:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(banner, field, value)
    await db.commit()
    await db.refresh(banner)
    return banner


async def list_slides(
    db: AsyncSession, banner_id: uuid.UUID, offset: int, limit: int
) -> tuple[list[HomeBannerSlide], int]:
    total = await db.scalar(
        select(func.count())
        .select_from(HomeBannerSlide)
        .where(HomeBannerSlide.banner_id == banner_id)
    )
    result = await db.execute(
        select(HomeBannerSlide)
        .where(HomeBannerSlide.banner_id == banner_id)
        .order_by(HomeBannerSlide.sort_order, HomeBannerSlide.created_at)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_slide(db: AsyncSession, slide_id: uuid.UUID) -> HomeBannerSlide:
    slide = await db.get(HomeBannerSlide, slide_id)
    if slide is None:
        raise NotFoundError("Banner slide not found")
    return slide


async def _slug_taken(db: AsyncSession, slug: str, slide_id: uuid.UUID | None = None) -> bool:
    existing = await db.scalar(select(HomeBannerSlide).where(HomeBannerSlide.slug == slug))
    return existing is not None and existing.id != slide_id


async def create_slide(
    db: AsyncSession, banner: HomeBanner, payload: BannerSlideWrite
) -> HomeBannerSlide:
    if await _slug_taken(db, payload.slug):
        raise ConflictError("A banner slide with this slug already exists")
    slide = HomeBannerSlide(banner_id=banner.id, **payload.model_dump())
    db.add(slide)
    await db.commit()
    await db.refresh(slide)
    return slide


async def update_slide(
    db: AsyncSession, slide: HomeBannerSlide, payload: BannerSlideUpdate
) -> HomeBannerSlide:
    data = payload.model_dump(exclude_unset=True)
    slug = data.get("slug")
    if slug is not None and await _slug_taken(db, slug, slide.id):
        raise ConflictError("A banner slide with this slug already exists")
    for field, value in data.items():
        setattr(slide, field, value)
    await db.commit()
    await db.refresh(slide)
    return slide


async def delete_slide(db: AsyncSession, slide: HomeBannerSlide) -> None:
    await db.delete(slide)
    await db.commit()


async def priority_slide_id(db: AsyncSession, banner_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(
        select(HomeBannerSlide.id)
        .where(
            HomeBannerSlide.banner_id == banner_id,
            HomeBannerSlide.is_published.is_(True),
        )
        .order_by(HomeBannerSlide.sort_order, HomeBannerSlide.created_at)
        .limit(1)
    )


async def is_priority_slide(db: AsyncSession, slide: HomeBannerSlide) -> bool:
    if not slide.is_published:
        return False
    return await priority_slide_id(db, slide.banner_id) == slide.id
