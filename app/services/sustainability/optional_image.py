from fastapi import UploadFile

from app.core.exceptions import UnprocessableError
from app.schemas.sustainability.optional_image import MISSING_ALT, OptionalImageWrite
from app.services.image_storage import delete_owned_media, read_image, store_image

MEDIA = "sustainability"


async def resolve_optional_image(
    image: OptionalImageWrite | None, upload: UploadFile | None, staged_message: str
) -> tuple[str, str, str | None]:
    """Return ``(src, alt, stored)`` for a section's optional photo.

    An upload wins over ``image.src``. No upload and no src means "no photo" (``src`` is
    ""). A photo without alt text is rejected. ``stored`` is the freshly stored media
    reference, if any, so the caller can delete it when the save fails later.
    """
    alt = image.alt if image is not None else ""
    stored: str | None = None
    if upload is not None and upload.filename:
        src = stored = store_image(await read_image(upload), folder=MEDIA)
    else:
        src = image.src if image is not None else ""
        if src.startswith("/uploads/") or src.startswith("blob:"):
            raise UnprocessableError(staged_message)
    if src and not alt:
        if stored:
            delete_owned_media({stored}, folder=MEDIA)
        raise UnprocessableError(MISSING_ALT)
    if not src:
        alt = ""
    return src, alt, stored
