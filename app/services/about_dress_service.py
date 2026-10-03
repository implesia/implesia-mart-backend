import uuid
from urllib.parse import quote

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.about_dress import (
    AboutDressBlock,
    AboutDressFeature,
    AboutDressImage,
    AboutDressSection,
)
from app.schemas.about_dress import (
    DressesPublic,
    DressFeatureRead,
    DressImageRead,
    DressPublic,
    DressRead,
    DressReorder,
    DressWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

SECTION_SLUG = "about"
MAX_DRESSES = 12
MAX_FEATURES = 8
MAX_IMAGES = 12
_MEDIA = "about"
_ORDER_MESSAGE = "হ্যালো, আমি একটি কাস্টম ডিজাইনের ড্রেস অর্ডার করতে চাই।"
DEFAULT_KICKER = "নতুন সংযোজন"
DEFAULT_TITLE = "শুধু গ্যাজেট নয়, আমরা তৈরি করি গর্জিয়াস ড্রেসও"
DEFAULT_SUBTITLE = (
    "ট্রেন্ডিং গ্যাজেটের পাশাপাশি এখন আমরা হাতে তৈরি করছি বাচ্চাদের ও নারীদের জন্য অসাধারণ "
    "গর্জিয়াস ড্রেস। আপনার পছন্দের ডিজাইন, কালার ও মাপ জানালেই আমরা বানিয়ে দিব ঠিক আপনার মনের মতো — "
    "সেরা ফেব্রিক ও ফিনিশিং কোয়ালিটি বজায় রেখে।"
)
DEFAULT_PRIMARY_LABEL = "কাস্টম অর্ডার"
DEFAULT_PRIMARY_HREF = f"https://wa.me/8801516527932?text={quote(_ORDER_MESSAGE, safe='')}"
DEFAULT_SECONDARY_LABEL = "গর্জিয়াস ড্রেস"
DEFAULT_SECONDARY_HREF = "/products?category=fashion"
DEFAULT_FEATURES: tuple[tuple[str, str, str], ...] = (
    ("design_services", "কাস্টম ডিজাইন", "আপনার পছন্দের ডিজাইন, কালার ও মাপ অনুযায়ী তৈরি করি।"),
    ("back_hand", "১০০% হাতে তৈরি", "প্রতিটি ড্রেস তৈরি হয় নিজ হাতে, যত্ন ও নিষ্ঠার সাথে।"),
    ("checkroom", "বাচ্চা ও নারীদের জন্য", "শিশুদের পার্টি ড্রেস থেকে নারীদের গর্জিয়াস গাউন — সবই পাবেন।"),
    ("verified", "প্রিমিয়াম কোয়ালিটি", "উন্নত ফেব্রিক আর নিখুঁত ফিনিশিং সবসময় আমাদের অগ্রাধিকার।"),
)
DEFAULT_IMAGES: tuple[tuple[str, str], ...] = (
    (
        "/images/products/baby-products/baby-frock-with-baby.jpeg",
        "হাতে তৈরি বেবি পার্টি ড্রেস — সরাসরি ব্যবহারের ছবি",
    ),
    (
        "/images/products/baby-products/female-gorgious-ground-dress.jpeg",
        "নারীদের জন্য হাতে তৈরি গর্জিয়াস গাউন",
    ),
    (
        "/images/products/baby-products/baby-ground-frog-more.jpeg",
        "পছন্দের কালারে কাস্টম তৈরি বেবি ড্রেস",
    ),
    (
        "/images/products/baby-products/baby-ground-frog-3.jpeg",
        "হাতে তৈরি বেবি পার্টি ড্রেস — বো ডিটেইল",
    ),
    (
        "/images/products/baby-products/3-quater-ground-frog2.jpeg",
        "হাতে তৈরি নিত্যদিনের ড্রেস",
    ),
    (
        "/images/products/baby-products/baby-jama-pant.jpeg",
        "বাচ্চাদের জন্য হাতে তৈরি কম্ফোর্টেবল সেট",
    ),
)
_BUTTON = "Add a link for each button that has a label, or clear the label."


def _features(rows: list[AboutDressFeature]) -> list[DressFeatureRead]:
    return [
        DressFeatureRead(id=row.id, icon=row.icon, title=row.title, description=row.description)
        for row in rows
    ]


def _images(rows: list[AboutDressImage]) -> list[DressImageRead]:
    return [DressImageRead(id=row.id, src=row.src, alt=row.alt) for row in rows]


def _read(
    block: AboutDressBlock,
    features: list[AboutDressFeature],
    images: list[AboutDressImage],
) -> DressRead:
    return DressRead(
        id=block.id,
        kicker=block.kicker,
        title=block.title,
        subtitle=block.subtitle,
        features=_features(features),
        primary_label=block.primary_label,
        primary_href=block.primary_href,
        secondary_label=block.secondary_label,
        secondary_href=block.secondary_href,
        is_active=block.is_active,
        images=_images(images),
    )


def _public(
    block: AboutDressBlock,
    features: list[AboutDressFeature],
    images: list[AboutDressImage],
) -> DressPublic:
    return DressPublic(
        id=block.id,
        kicker=block.kicker,
        title=block.title,
        subtitle=block.subtitle,
        features=_features(features),
        primary_label=block.primary_label,
        primary_href=block.primary_href,
        secondary_label=block.secondary_label,
        secondary_href=block.secondary_href,
        images=_images(images),
    )


async def _blocks(
    db: AsyncSession, section_id: uuid.UUID, *, active_only: bool
) -> list[AboutDressBlock]:
    query = select(AboutDressBlock).where(AboutDressBlock.section_id == section_id)
    if active_only:
        query = query.where(AboutDressBlock.is_active.is_(True))
    query = query.order_by(AboutDressBlock.sort_order, AboutDressBlock.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def _feature_rows(db: AsyncSession, dress_id: uuid.UUID) -> list[AboutDressFeature]:
    result = await db.execute(
        select(AboutDressFeature)
        .where(AboutDressFeature.dress_id == dress_id)
        .order_by(AboutDressFeature.sort_order, AboutDressFeature.created_at)
    )
    return list(result.scalars().all())


async def _image_rows(db: AsyncSession, dress_id: uuid.UUID) -> list[AboutDressImage]:
    result = await db.execute(
        select(AboutDressImage)
        .where(AboutDressImage.dress_id == dress_id)
        .order_by(AboutDressImage.sort_order, AboutDressImage.created_at)
    )
    return list(result.scalars().all())


async def _present(db: AsyncSession, block: AboutDressBlock) -> DressRead:
    return _read(block, await _feature_rows(db, block.id), await _image_rows(db, block.id))


async def ensure_section(db: AsyncSession) -> AboutDressSection:
    row = await db.scalar(select(AboutDressSection).where(AboutDressSection.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = AboutDressSection(slug=SECTION_SLUG)
    db.add(row)
    await db.flush()
    block = AboutDressBlock(
        section_id=row.id,
        kicker=DEFAULT_KICKER,
        title=DEFAULT_TITLE,
        subtitle=DEFAULT_SUBTITLE,
        primary_label=DEFAULT_PRIMARY_LABEL,
        primary_href=DEFAULT_PRIMARY_HREF,
        secondary_label=DEFAULT_SECONDARY_LABEL,
        secondary_href=DEFAULT_SECONDARY_HREF,
        is_active=True,
        sort_order=0,
    )
    db.add(block)
    await db.flush()
    for index, (icon, title, description) in enumerate(DEFAULT_FEATURES):
        db.add(
            AboutDressFeature(
                dress_id=block.id,
                icon=icon,
                title=title,
                description=description,
                sort_order=index,
            )
        )
    for index, (src, alt) in enumerate(DEFAULT_IMAGES):
        db.add(AboutDressImage(dress_id=block.id, src=src, alt=alt, sort_order=index))
    await db.commit()
    await db.refresh(row)
    return row


async def list_dresses(db: AsyncSession) -> list[DressRead]:
    row = await ensure_section(db)
    return [await _present(db, block) for block in await _blocks(db, row.id, active_only=False)]


async def public_dresses(db: AsyncSession) -> DressesPublic:
    row = await ensure_section(db)
    items: list[DressPublic] = []
    for block in await _blocks(db, row.id, active_only=True):
        items.append(
            _public(block, await _feature_rows(db, block.id), await _image_rows(db, block.id))
        )
    return DressesPublic(items=items)


async def get_dress(db: AsyncSession, dress_id: uuid.UUID) -> AboutDressBlock:
    block = await db.get(AboutDressBlock, dress_id)
    if block is None:
        raise NotFoundError("Custom dress not found")
    return block


def _check(payload: DressWrite) -> None:
    if len(payload.features) > MAX_FEATURES:
        raise UnprocessableError("You can add up to 8 highlights")
    if len(payload.images) > MAX_IMAGES:
        raise UnprocessableError("You can add up to 12 photos")
    if not payload.title and not payload.subtitle and not payload.features:
        raise UnprocessableError("Add a title or some text.")
    missing_link = (payload.primary_label and not payload.primary_href) or (
        payload.secondary_label and not payload.secondary_href
    )
    if missing_link:
        raise UnprocessableError(_BUTTON)


def _reject_staged_path(src: str) -> None:
    if src.startswith("/uploads/") or src.startswith("blob:"):
        raise UnprocessableError("Send the image file with the custom dress")


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


async def _resolve_images(
    payload: DressWrite, uploads: dict[int, UploadFile]
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
    block: AboutDressBlock,
    payload: DressWrite,
    images: list[tuple[str, str]],
) -> set[str]:
    existing_features = await _feature_rows(db, block.id)
    for index, feature in enumerate(payload.features):
        if index < len(existing_features):
            existing_features[index].icon = feature.icon
            existing_features[index].title = feature.title
            existing_features[index].description = feature.description
            existing_features[index].sort_order = index
        else:
            db.add(
                AboutDressFeature(
                    dress_id=block.id,
                    icon=feature.icon,
                    title=feature.title,
                    description=feature.description,
                    sort_order=index,
                )
            )
    for extra in existing_features[len(payload.features) :]:
        await db.delete(extra)

    existing_images = await _image_rows(db, block.id)
    previous = owned_refs(*(item.src for item in existing_images), folder=_MEDIA)
    for index, (src, alt) in enumerate(images):
        if index < len(existing_images):
            existing_images[index].src = src
            existing_images[index].alt = alt
            existing_images[index].sort_order = index
        else:
            db.add(AboutDressImage(dress_id=block.id, src=src, alt=alt, sort_order=index))
    for extra in existing_images[len(images) :]:
        await db.delete(extra)
    return previous


def _apply(block: AboutDressBlock, payload: DressWrite) -> None:
    block.kicker = payload.kicker
    block.title = payload.title
    block.subtitle = payload.subtitle
    block.primary_label = payload.primary_label
    block.primary_href = payload.primary_href
    block.secondary_label = payload.secondary_label
    block.secondary_href = payload.secondary_href
    block.is_active = payload.is_active


async def create_dress(
    db: AsyncSession, payload: DressWrite, uploads: dict[int, UploadFile]
) -> DressRead:
    _check(payload)
    section = await ensure_section(db)
    count = await db.scalar(
        select(func.count())
        .select_from(AboutDressBlock)
        .where(AboutDressBlock.section_id == section.id)
    )
    if int(count or 0) >= MAX_DRESSES:
        raise UnprocessableError("You can show up to 12 custom dresses")
    current = await db.scalar(
        select(func.max(AboutDressBlock.sort_order)).where(AboutDressBlock.section_id == section.id)
    )
    resolved, stored = await _resolve_images(payload, uploads)
    block = AboutDressBlock(
        section_id=section.id,
        sort_order=0 if current is None else int(current) + 1,
        kicker="",
        title="",
        subtitle="",
        primary_label="",
        primary_href="",
        secondary_label="",
        secondary_href="",
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


async def update_dress(
    db: AsyncSession,
    block: AboutDressBlock,
    payload: DressWrite,
    uploads: dict[int, UploadFile],
) -> DressRead:
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


async def delete_dress(db: AsyncSession, block: AboutDressBlock) -> None:
    images = await _image_rows(db, block.id)
    owned = owned_refs(*(item.src for item in images), folder=_MEDIA)
    await db.delete(block)
    await db.commit()
    delete_owned_media(owned, folder=_MEDIA)


async def reorder(db: AsyncSession, payload: DressReorder) -> list[DressRead]:
    section = await ensure_section(db)
    blocks = await _blocks(db, section.id, active_only=False)
    current = {block.id for block in blocks}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every custom dress in the new order")
    order = {dress_id: index for index, dress_id in enumerate(incoming)}
    for block in blocks:
        block.sort_order = order[block.id]
    await db.commit()
    ordered = await _blocks(db, section.id, active_only=False)
    return [await _present(db, block) for block in ordered]
