from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.home.popup import HomePopup
from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.home.popup import PopupAdmin, PopupPublic, PopupWrite
from app.services.image_storage import delete_owned_media, read_image, store_image

POPUP_SLUG = "home"
_FOLDER = "popup"
_PREFIX = f"/media/{_FOLDER}/"


async def _row(db: AsyncSession) -> HomePopup | None:
    return await db.scalar(select(HomePopup).where(HomePopup.slug == POPUP_SLUG))


def _safe(value: str) -> str:
    return value if cover_ref_ok(value) else ""


async def public_view(db: AsyncSession) -> PopupPublic | None:
    """Return the active storefront popup config, or None when disabled/empty."""
    row = await _row(db)
    if row is None or not row.is_active:
        return None
    image = _safe(row.image_src)
    if not row.heading and not image:
        return None
    href = _safe(row.cta_href)
    label = row.cta_label if href else ""
    version = str(int(row.updated_at.timestamp())) if row.updated_at else "1"
    return PopupPublic(
        badge_text=row.badge_text,
        heading=row.heading,
        body=row.body,
        coupon_code=row.coupon_code,
        cta_label=label,
        cta_href=href if label else "",
        image_src=image,
        image_alt=row.image_alt or row.heading,
        delay_seconds=row.delay_seconds,
        min_scroll_px=row.min_scroll_px,
        dismiss_cooldown_hours=row.dismiss_cooldown_hours,
        show_on_all_pages=row.show_on_all_pages,
        version=version,
    )


async def admin_view(db: AsyncSession) -> PopupAdmin:
    row = await _row(db)
    if row is None:
        return PopupAdmin(
            is_active=False,
            badge_text="",
            heading="",
            body="",
            coupon_code="",
            cta_label="",
            cta_href="",
            image_src="",
            image_alt="",
            delay_seconds=4,
            min_scroll_px=150,
            dismiss_cooldown_hours=24,
            show_on_all_pages=True,
        )
    return PopupAdmin(
        is_active=row.is_active,
        badge_text=row.badge_text,
        heading=row.heading,
        body=row.body,
        coupon_code=row.coupon_code,
        cta_label=row.cta_label,
        cta_href=row.cta_href,
        image_src=_safe(row.image_src),
        image_alt=row.image_alt,
        delay_seconds=row.delay_seconds,
        min_scroll_px=row.min_scroll_px,
        dismiss_cooldown_hours=row.dismiss_cooldown_hours,
        show_on_all_pages=row.show_on_all_pages,
        image_needs_upload=bool(row.image_src) and not _safe(row.image_src),
    )


async def update(db: AsyncSession, payload: PopupWrite) -> PopupAdmin:
    row = await _row(db)
    previous = ""
    if row is None:
        row = HomePopup(slug=POPUP_SLUG)
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
    """Validate and store one popup image under `/media/popup/`."""
    if not upload.filename:
        raise UnprocessableError("Choose an image file.")
    return store_image(await read_image(upload), folder=_FOLDER)
