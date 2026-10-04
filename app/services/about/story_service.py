import uuid

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.about.story import (
    AboutStoryBlock,
    AboutStoryImage,
    AboutStoryParagraph,
    AboutStorySection,
)
from app.schemas.about.story import (
    StoriesPublic,
    StoryImageRead,
    StoryParagraphRead,
    StoryPublic,
    StoryRead,
    StoryReorder,
    StoryWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

SECTION_SLUG = "about"
MAX_STORIES = 12
MAX_PARAGRAPHS = 8
MAX_IMAGES = 6
_MEDIA = "about"
DEFAULT_KICKER = "আমাদের যাত্রা"
DEFAULT_TITLE = "কেন ইমপ্লেসিয়া মার্ট শুরু হলো"
DEFAULT_PARAGRAPHS = (
    "অনলাইনে অর্ডার করা মানেই ছিল একরাশ দুশ্চিন্তা — প্রোডাক্ট আসল কিনা, কোয়ালিটি ঠিক থাকবে কিনা, "
    "আগে টাকা দিয়ে ঠকে যাব কিনা। আমরা লক্ষ্য করলাম, সমস্যাটা প্রোডাক্টে নয়, বিশ্বাসে।",
    "তাই ইমপ্লেসিয়া মার্টে প্রতিটি প্রোডাক্ট অর্ডারের আগে নিজেরা চালিয়ে দেখি, যাচাই করি, এবং "
    "সারাদেশে ক্যাশ অন ডেলিভারি সুবিধা রাখি — যাতে আপনি প্রোডাক্ট হাতে পেয়ে, নিজে দেখে তারপর টাকা "
    "দিতে পারেন।",
    "শুরুটা হয়েছিল হাতে গোনা কিছু ট্রেন্ডিং গ্যাজেট নিয়ে, কিন্তু আমাদের লক্ষ্য তার চেয়ে অনেক বড় — "
    "প্রতিদিনের প্রয়োজনীয় থেকে শুরু করে জনপ্রিয় নানা ক্যাটাগরির প্রোডাক্ট, একই বিশ্বাসযোগ্যতা আর "
    "কোয়ালিটি স্ট্যান্ডার্ড মেনে, ধাপে ধাপে আপনার দরজায় পৌঁছে দেওয়াই আমাদের আসল লক্ষ্য।",
)
DEFAULT_CTA_LABEL = "সব প্রোডাক্ট"
DEFAULT_CTA_HREF = "/products"
DEFAULT_IMAGES: tuple[tuple[str, str], ...] = (
    ("/images/products/lamp/lamp-2.jpg", "সানসেট ল্যাম্প — কোয়ালিটি চেক করা গ্যাজেট"),
    ("/images/products/baby-products/baby-frock-with-baby.jpeg", "হাতে তৈরি বেবি পার্টি ফ্রক"),
)


def _paragraphs(rows: list[AboutStoryParagraph]) -> list[StoryParagraphRead]:
    return [StoryParagraphRead(id=row.id, text=row.body) for row in rows]


def _images(rows: list[AboutStoryImage]) -> list[StoryImageRead]:
    return [StoryImageRead(id=row.id, src=row.src, alt=row.alt) for row in rows]


def _read(
    block: AboutStoryBlock,
    paragraphs: list[AboutStoryParagraph],
    images: list[AboutStoryImage],
) -> StoryRead:
    return StoryRead(
        id=block.id,
        kicker=block.kicker,
        title=block.title,
        paragraphs=_paragraphs(paragraphs),
        cta_label=block.cta_label,
        cta_href=block.cta_href,
        is_active=block.is_active,
        images=_images(images),
    )


def _public(
    block: AboutStoryBlock,
    paragraphs: list[AboutStoryParagraph],
    images: list[AboutStoryImage],
) -> StoryPublic:
    return StoryPublic(
        id=block.id,
        kicker=block.kicker,
        title=block.title,
        paragraphs=_paragraphs(paragraphs),
        cta_label=block.cta_label,
        cta_href=block.cta_href,
        images=_images(images),
    )


async def _blocks(
    db: AsyncSession, section_id: uuid.UUID, *, active_only: bool
) -> list[AboutStoryBlock]:
    query = select(AboutStoryBlock).where(AboutStoryBlock.section_id == section_id)
    if active_only:
        query = query.where(AboutStoryBlock.is_active.is_(True))
    query = query.order_by(AboutStoryBlock.sort_order, AboutStoryBlock.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _paragraph_rows(db: AsyncSession, story_id: uuid.UUID) -> list[AboutStoryParagraph]:
    result = await db.execute(
        select(AboutStoryParagraph)
        .where(AboutStoryParagraph.story_id == story_id)
        .order_by(AboutStoryParagraph.sort_order, AboutStoryParagraph.created_at)
    )
    return list(result.scalars().all())


async def _image_rows(db: AsyncSession, story_id: uuid.UUID) -> list[AboutStoryImage]:
    result = await db.execute(
        select(AboutStoryImage)
        .where(AboutStoryImage.story_id == story_id)
        .order_by(AboutStoryImage.sort_order, AboutStoryImage.created_at)
    )
    return list(result.scalars().all())


async def _present(db: AsyncSession, block: AboutStoryBlock) -> StoryRead:
    return _read(
        block,
        await _paragraph_rows(db, block.id),
        await _image_rows(db, block.id),
    )


async def ensure_section(db: AsyncSession) -> AboutStorySection:
    row = await db.scalar(select(AboutStorySection).where(AboutStorySection.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = AboutStorySection(slug=SECTION_SLUG)
    db.add(row)
    await db.flush()
    block = AboutStoryBlock(
        section_id=row.id,
        kicker=DEFAULT_KICKER,
        title=DEFAULT_TITLE,
        cta_label=DEFAULT_CTA_LABEL,
        cta_href=DEFAULT_CTA_HREF,
        is_active=True,
        sort_order=0,
    )
    db.add(block)
    await db.flush()
    for index, text in enumerate(DEFAULT_PARAGRAPHS):
        db.add(AboutStoryParagraph(story_id=block.id, body=text, sort_order=index))
    for index, (src, alt) in enumerate(DEFAULT_IMAGES):
        db.add(AboutStoryImage(story_id=block.id, src=src, alt=alt, sort_order=index))
    await db.commit()
    await db.refresh(row)
    return row


async def list_stories(db: AsyncSession) -> list[StoryRead]:
    row = await ensure_section(db)
    blocks = await _blocks(db, row.id, active_only=False)
    return [await _present(db, block) for block in blocks]


async def public_stories(db: AsyncSession) -> StoriesPublic:
    row = await ensure_section(db)
    blocks = await _blocks(db, row.id, active_only=True)
    items: list[StoryPublic] = []
    for block in blocks:
        items.append(
            _public(
                block,
                await _paragraph_rows(db, block.id),
                await _image_rows(db, block.id),
            )
        )
    return StoriesPublic(items=items)


async def get_story(db: AsyncSession, story_id: uuid.UUID) -> AboutStoryBlock:
    block = await db.get(AboutStoryBlock, story_id)
    if block is None:
        raise NotFoundError("Story not found")
    return block


def _check(payload: StoryWrite) -> None:
    if len(payload.paragraphs) > MAX_PARAGRAPHS:
        raise UnprocessableError("You can add up to 8 paragraphs")
    if len(payload.images) > MAX_IMAGES:
        raise UnprocessableError("You can add up to 6 photos")
    if not payload.title and not payload.paragraphs:
        raise UnprocessableError("Add a title or some story text.")
    if payload.cta_label and not payload.cta_href:
        raise UnprocessableError("Add a link for the button, or clear the button label.")


def _reject_staged_path(src: str) -> None:
    if src.startswith("/uploads/") or src.startswith("blob:"):
        raise UnprocessableError("Send the image file with the story")


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


async def _resolve_images(
    payload: StoryWrite, uploads: dict[int, UploadFile]
) -> tuple[list[tuple[str, str]], list[str]]:
    stored: list[str] = []
    resolved: list[tuple[str, str]] = []
    try:
        for index, image in enumerate(payload.images):
            taken = await _take_image(uploads.get(index))
            if taken is not None:
                stored.append(taken)
                src = taken
            else:
                src = image.src
                if not src:
                    raise UnprocessableError("Add an image, or remove the empty photo.")
                _reject_staged_path(src)
            resolved.append((src, image.alt))
    except Exception:
        delete_owned_media(set(stored), folder=_MEDIA)
        raise
    return resolved, stored


async def _write_children(
    db: AsyncSession,
    block: AboutStoryBlock,
    payload: StoryWrite,
    images: list[tuple[str, str]],
) -> set[str]:
    existing_paragraphs = await _paragraph_rows(db, block.id)
    texts = [item.text for item in payload.paragraphs]
    for index, text in enumerate(texts):
        if index < len(existing_paragraphs):
            existing_paragraphs[index].body = text
            existing_paragraphs[index].sort_order = index
        else:
            db.add(AboutStoryParagraph(story_id=block.id, body=text, sort_order=index))
    for extra in existing_paragraphs[len(texts) :]:
        await db.delete(extra)

    existing_images = await _image_rows(db, block.id)
    previous = owned_refs(*(item.src for item in existing_images), folder=_MEDIA)
    for index, (src, alt) in enumerate(images):
        if index < len(existing_images):
            existing_images[index].src = src
            existing_images[index].alt = alt
            existing_images[index].sort_order = index
        else:
            db.add(AboutStoryImage(story_id=block.id, src=src, alt=alt, sort_order=index))
    for stale in existing_images[len(images) :]:
        await db.delete(stale)
    return previous


def _apply(block: AboutStoryBlock, payload: StoryWrite) -> None:
    block.kicker = payload.kicker
    block.title = payload.title
    block.cta_label = payload.cta_label
    block.cta_href = payload.cta_href
    block.is_active = payload.is_active


async def create_story(
    db: AsyncSession, payload: StoryWrite, uploads: dict[int, UploadFile]
) -> StoryRead:
    _check(payload)
    section = await ensure_section(db)
    count = await db.scalar(
        select(func.count())
        .select_from(AboutStoryBlock)
        .where(AboutStoryBlock.section_id == section.id)
    )
    if int(count or 0) >= MAX_STORIES:
        raise UnprocessableError("You can show up to 12 stories")
    current = await db.scalar(
        select(func.max(AboutStoryBlock.sort_order)).where(
            AboutStoryBlock.section_id == section.id
        )
    )
    resolved, stored = await _resolve_images(payload, uploads)
    block = AboutStoryBlock(
        section_id=section.id,
        sort_order=0 if current is None else int(current) + 1,
        kicker="",
        title="",
        cta_label="",
        cta_href="",
        is_active=True,
    )
    db.add(block)
    await db.flush()
    try:
        await _write_children(db, block, payload, resolved)
        _apply(block, payload)
        await db.commit()
    except Exception:
        delete_owned_media(set(stored), folder=_MEDIA)
        raise
    await db.refresh(block)
    return await _present(db, block)


async def update_story(
    db: AsyncSession,
    block: AboutStoryBlock,
    payload: StoryWrite,
    uploads: dict[int, UploadFile],
) -> StoryRead:
    _check(payload)
    resolved, stored = await _resolve_images(payload, uploads)
    try:
        previous = await _write_children(db, block, payload, resolved)
        _apply(block, payload)
        await db.commit()
    except Exception:
        delete_owned_media(set(stored), folder=_MEDIA)
        raise
    await db.refresh(block)
    current = await _image_rows(db, block.id)
    kept = owned_refs(*(item.src for item in current), folder=_MEDIA)
    delete_owned_media(previous - kept, folder=_MEDIA)
    return await _present(db, block)


async def delete_story(db: AsyncSession, block: AboutStoryBlock) -> None:
    images = await _image_rows(db, block.id)
    owned = owned_refs(*(item.src for item in images), folder=_MEDIA)
    await db.delete(block)
    await db.commit()
    delete_owned_media(owned, folder=_MEDIA)


async def reorder(db: AsyncSession, payload: StoryReorder) -> list[StoryRead]:
    section = await ensure_section(db)
    blocks = await _blocks(db, section.id, active_only=False)
    current = {block.id for block in blocks}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every story in the new order")
    order = {story_id: index for index, story_id in enumerate(incoming)}
    for block in blocks:
        block.sort_order = order[block.id]
    await db.commit()
    return [await _present(db, block) for block in await _blocks(db, section.id, active_only=False)]
