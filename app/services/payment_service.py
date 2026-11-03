"""Store payment settings (the Bangla QR image) and the Bangla QR advance split."""

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.payment_settings import PaymentSettings
from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.payment import (
    ADVANCE_PERCENTS,
    AdvanceOption,
    PaymentSettingsAdmin,
    PaymentSettingsPublic,
)
from app.services.image_storage import delete_owned_media, read_image, store_image

SETTINGS_SLUG = "main"
_FOLDER = "payment"
_PREFIX = f"/media/{_FOLDER}/"


def advance_split(total: int, percent: int) -> tuple[int, int]:
    """(advance, due) for a Bangla QR order. Advance is rounded up to whole taka.

    Integer maths only: ceil(total * percent / 100) = -(-total * percent // 100).
    """
    if percent not in ADVANCE_PERCENTS:
        raise UnprocessableError("Choose 25, 50, 75 or 100 percent")
    total = max(total, 0)
    advance = min(total, -(-total * percent // 100))
    return advance, total - advance


def advance_options(total: int) -> list[AdvanceOption]:
    options = []
    for percent in ADVANCE_PERCENTS:
        advance, due = advance_split(total, percent)
        options.append(AdvanceOption(percent=percent, advance=advance, due=due))
    return options


async def _row(db: AsyncSession) -> PaymentSettings | None:
    return await db.scalar(select(PaymentSettings).where(PaymentSettings.slug == SETTINGS_SLUG))


def _usable(value: str) -> str | None:
    return value if value and cover_ref_ok(value) else None


async def bangla_qr_src(db: AsyncSession) -> str | None:
    """The configured QR image, or None (not set, or an unusable stored value)."""
    row = await _row(db)
    return _usable(row.bangla_qr_src) if row is not None else None


async def public_view(db: AsyncSession) -> PaymentSettingsPublic:
    src = await bangla_qr_src(db)
    return PaymentSettingsPublic(bangla_qr_src=src, bangla_qr_enabled=src is not None)


async def admin_view(db: AsyncSession) -> PaymentSettingsAdmin:
    return PaymentSettingsAdmin(**(await public_view(db)).model_dump())


async def _set(db: AsyncSession, value: str) -> PaymentSettingsAdmin:
    row = await _row(db)
    if row is None:
        row = PaymentSettings(slug=SETTINGS_SLUG, bangla_qr_src="")
        db.add(row)
    previous = row.bangla_qr_src
    row.bangla_qr_src = value
    await db.commit()
    if previous and previous != value and previous.startswith(_PREFIX):
        delete_owned_media({previous}, folder=_FOLDER)
    return await admin_view(db)


async def upload_qr(db: AsyncSession, upload: UploadFile) -> PaymentSettingsAdmin:
    """Store a new QR image (JPEG/PNG/WEBP/GIF by bytes, 5 MB) and replace the old one."""
    if not upload.filename:
        raise UnprocessableError("Choose an image file.")
    return await _set(db, store_image(await read_image(upload), folder=_FOLDER))


async def delete_qr(db: AsyncSession) -> PaymentSettingsAdmin:
    """Remove the QR. The product page card and the checkout method disappear."""
    return await _set(db, "")
