import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.home.faq import HomeFaq, HomeFaqItem
from app.schemas.home.faq import (
    FaqAdmin,
    FaqCopyUpdate,
    FaqItemPublic,
    FaqItemRead,
    FaqItemUpdate,
    FaqItemWrite,
    FaqPublic,
    FaqReorder,
)

FAQ_SLUG = "home"
MAX_ITEMS = 24
DEFAULT_KICKER = "জিজ্ঞাসা ও উত্তর"
DEFAULT_TITLE = "প্রায়শই জিজ্ঞাসিত প্রশ্ন"
DEFAULT_SUBTITLE = "অর্ডার, পেমেন্ট, ডেলিভারি ও রিটার্ন নিয়ে সাধারণ প্রশ্নের দ্রুত উত্তর।"
DEFAULT_MORE_LABEL = "আরও প্রশ্ন দেখুন"
DEFAULT_MORE_HREF = "/faqs"
DEFAULTS: tuple[dict[str, object], ...] = (
    {
        "category": "অর্ডার ট্র্যাকিং",
        "question": "আমার অর্ডার কীভাবে ট্র্যাক করব?",
        "answer": (
            "আমার অর্ডার পেজে অর্ডার নম্বর আর চেকআউটের মোবাইল দিলে স্ট্যাটাস দেখা যায়। "
            "একই ব্রাউজারে করলে নম্বর সেভ থাকে। দরকার হলে কল বা হোয়াটসঅ্যাপেও জানানো হয়।"
        ),
        "sort_order": 0,
    },
    {
        "category": "পেমেন্ট ও ক্যাশ অন ডেলিভারি",
        "question": "অর্ডারের জন্য কি আগে টাকা পরিশোধ করতে হবে?",
        "answer": (
            "না। আমরা পুরো বাংলাদেশে ক্যাশ অন ডেলিভারি সুবিধা দিচ্ছি — "
            "প্রোডাক্ট হাতে পেয়ে, ভালোভাবে দেখে তারপর টাকা পরিশোধ করতে পারবেন।"
        ),
        "sort_order": 1,
    },
    {
        "category": "রিটার্ন ও রিপ্লেসমেন্ট",
        "question": "প্রোডাক্ট পছন্দ না হলে রিটার্ন করা যাবে?",
        "answer": (
            "হ্যাঁ। প্রোডাক্ট ড্যামেজ বা ভুল হলে ডেলিভারির ৩ দিনের মধ্যে জানালে "
            "আমরা রিটার্ন বা রিপ্লেসমেন্ট প্রক্রিয়া সম্পন্ন করে দিই।"
        ),
        "sort_order": 2,
    },
    {
        "category": "কাস্টমার সাপোর্ট",
        "question": "কোনো সমস্যা হলে কীভাবে যোগাযোগ করব?",
        "answer": (
            "আমাদের কাস্টমার সাপোর্ট টিম ফোন, ফেসবুক পেজ ও ওয়েবসাইটের যোগাযোগ ফর্মের "
            "মাধ্যমে সবসময় সাহায্যের জন্য প্রস্তুত। আমরা দ্রুততম সময়ে উত্তর দেওয়ার চেষ্টা করি।"
        ),
        "sort_order": 3,
    },
    {
        "category": "প্রোডাক্ট কোয়ালিটি",
        "question": "প্রোডাক্টগুলো কি কোয়ালিটি চেক করা হয়?",
        "answer": (
            "হ্যাঁ। ডেলিভারির আগে প্রতিটি প্রোডাক্ট চালু করে পরীক্ষা করা হয়, "
            "যাতে আপনার হাতে পৌঁছায় সম্পূর্ণ কার্যকর একটি প্রোডাক্ট।"
        ),
        "sort_order": 4,
    },
    {
        "category": "ডেলিভারি সময়",
        "question": "ডেলিভারি পেতে কত সময় লাগে?",
        "answer": ("ঢাকার ভেতরে সাধারণত ২৪-৪৮ ঘণ্টা এবং ঢাকার বাইরে ২৪-৭২ ঘণ্টার মধ্যে ডেলিভারি সম্পন্ন হয়।"),
        "sort_order": 5,
    },
)


def present(item: HomeFaqItem) -> FaqItemRead:
    return FaqItemRead.model_validate(item)


def _section(row: HomeFaq, items: list[HomeFaqItem]) -> FaqAdmin:
    return FaqAdmin(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        more_label=row.more_label,
        more_href=row.more_href,
        items=[present(item) for item in items],
    )


async def _items(db: AsyncSession, faq_id: uuid.UUID, *, active_only: bool) -> list[HomeFaqItem]:
    query = select(HomeFaqItem).where(HomeFaqItem.faq_id == faq_id)
    if active_only:
        query = query.where(HomeFaqItem.is_active.is_(True))
    query = query.order_by(HomeFaqItem.sort_order, HomeFaqItem.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_faq(db: AsyncSession) -> HomeFaq:
    row = await db.scalar(select(HomeFaq).where(HomeFaq.slug == FAQ_SLUG))
    if row is not None:
        return row
    row = HomeFaq(
        slug=FAQ_SLUG,
        kicker=DEFAULT_KICKER,
        title=DEFAULT_TITLE,
        subtitle=DEFAULT_SUBTITLE,
        more_label=DEFAULT_MORE_LABEL,
        more_href=DEFAULT_MORE_HREF,
    )
    db.add(row)
    await db.flush()
    for raw in DEFAULTS:
        db.add(HomeFaqItem(faq_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> FaqAdmin:
    row = await ensure_faq(db)
    return _section(row, await _items(db, row.id, active_only=False))


async def public_view(db: AsyncSession) -> FaqPublic:
    row = await ensure_faq(db)
    items = await _items(db, row.id, active_only=True)
    return FaqPublic(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        more_label=row.more_label,
        more_href=row.more_href,
        items=[
            FaqItemPublic(
                id=item.id,
                category=item.category,
                question=item.question,
                answer=item.answer,
            )
            for item in items
        ],
    )


async def update_copy(db: AsyncSession, payload: FaqCopyUpdate) -> FaqAdmin:
    row = await ensure_faq(db)
    row.kicker = payload.kicker
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.more_label = payload.more_label
    row.more_href = payload.more_href
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> HomeFaqItem:
    item = await db.get(HomeFaqItem, item_id)
    if item is None:
        raise NotFoundError("Question not found")
    return item


async def create_item(db: AsyncSession, payload: FaqItemWrite) -> FaqItemRead:
    row = await ensure_faq(db)
    count = await db.scalar(
        select(func.count()).select_from(HomeFaqItem).where(HomeFaqItem.faq_id == row.id)
    )
    if int(count or 0) >= MAX_ITEMS:
        raise UnprocessableError("You can show up to 24 questions")
    current = await db.scalar(
        select(func.max(HomeFaqItem.sort_order)).where(HomeFaqItem.faq_id == row.id)
    )
    item = HomeFaqItem(
        faq_id=row.id,
        sort_order=0 if current is None else int(current) + 1,
        **payload.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(db: AsyncSession, item: HomeFaqItem, payload: FaqItemUpdate) -> FaqItemRead:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: HomeFaqItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: FaqReorder) -> FaqAdmin:
    row = await ensure_faq(db)
    items = await _items(db, row.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every question in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
