from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.home.promo import HomePromo
from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.home.promo import PromoAdmin, PromoPublic, PromoWrite
from app.services.image_storage import delete_owned_media, read_image, store_image

PROMO_SLUG = "home"
_FOLDER = "promo"
_PREFIX = f"/media/{_FOLDER}/"


async def _row(db: AsyncSession) -> HomePromo | None:
    return await db.scalar(select(HomePromo).where(HomePromo.slug == PROMO_SLUG))


def _safe(value: str) -> str:
    """A stored value the storefront can use, or "" for a legacy or unusable one."""
    return value if cover_ref_ok(value) else ""


async def public_view(db: AsyncSession) -> PromoPublic | None:
    """The live banner, or None. Never invents content: no row, hidden, or no usable image
    and description all mean the storefront shows nothing."""
    row = await _row(db)
    if row is None or not row.is_active:
        return None
    image = _safe(row.image_src)
    if not image or not row.image_alt:
        return None
    href = _safe(row.cta_href)
    label = row.cta_label if href else ""
    return PromoPublic(
        eyebrow=row.eyebrow,
        heading=row.heading,
        body=row.body,
        cta_label=label,
        cta_href=href if label else "",
        image_src=image,
        image_alt=row.image_alt,
        focal_x=row.focal_x,
        focal_y=row.focal_y,
        tone="light" if row.tone == "light" else "dark",
    )


async def admin_view(db: AsyncSession) -> PromoAdmin:
    row = await _row(db)
    if row is None:
        return PromoAdmin(
            is_active=False,
            eyebrow="",
            heading="",
            body="",
            cta_label="",
            cta_href="",
            image_src="",
            image_alt="",
            focal_x=50,
            focal_y=50,
            tone="dark",
        )
    return PromoAdmin(
        is_active=row.is_active,
        eyebrow=row.eyebrow,
        heading=row.heading,
        body=row.body,
        cta_label=row.cta_label,
        cta_href=row.cta_href,
        image_src=_safe(row.image_src),
        image_alt=row.image_alt,
        focal_x=row.focal_x,
        focal_y=row.focal_y,
        tone="light" if row.tone == "light" else "dark",
        image_needs_upload=bool(row.image_src) and not _safe(row.image_src),
    )


async def update(db: AsyncSession, payload: PromoWrite) -> PromoAdmin:
    row = await _row(db)
    previous = ""
    if row is None:
        row = HomePromo(slug=PROMO_SLUG)
        db.add(row)
    else:
        previous = row.image_src
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    await db.commit()
    if (
        previous
        and previous != payload.image_src
        and previous.startswith(_PREFIX)
        and cover_ref_ok(previous)
    ):
        delete_owned_media({previous}, folder=_FOLDER)
    return await admin_view(db)


async def upload_image(upload: UploadFile) -> str:
    """Validate (type by bytes, size) and store one banner image: `/media/promo/..`."""
    if not upload.filename:
        raise UnprocessableError("Choose an image file.")
    return store_image(await read_image(upload), folder=_FOLDER)
