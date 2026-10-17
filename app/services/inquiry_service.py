import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.inquiry import Inquiry, InquiryStatus, InquiryType
from app.models.user import User
from app.schemas.common import page_count
from app.schemas.inquiry import (
    EMPTY_MESSAGE,
    InquiryAdmin,
    InquiryCounts,
    InquiryCreate,
    InquiryList,
    InquiryQuery,
    InquiryReceipt,
    InquiryUpdate,
)

# A person needs a moment to type; a script posting instantly is treated as a bot.
MIN_FILL_MS = 1500


def is_bot(payload: InquiryCreate) -> bool:
    if payload.website.strip():
        return True
    return payload.elapsed_ms is not None and payload.elapsed_ms < MIN_FILL_MS


def decoy_receipt() -> InquiryReceipt:
    """Same shape as a real receipt, so a bot cannot tell it was dropped."""
    return InquiryReceipt(id=uuid.uuid4())


async def replayed(db: AsyncSession, key: str | None) -> InquiryReceipt | None:
    if not key:
        return None
    row = await db.scalar(select(Inquiry).where(Inquiry.idempotency_key == key))
    return InquiryReceipt(id=row.public_id) if row else None


async def create_inquiry(
    db: AsyncSession, payload: InquiryCreate, idempotency_key: str | None
) -> InquiryReceipt:
    if not payload.has_content():
        raise UnprocessableError(EMPTY_MESSAGE)
    if payload.type == InquiryType.NEWSLETTER and payload.email:
        # One subscription per address; a repeat sign-up returns the existing one.
        existing = await db.scalar(
            select(Inquiry).where(
                Inquiry.type == InquiryType.NEWSLETTER.value, Inquiry.email == payload.email
            )
        )
        if existing is not None:
            return InquiryReceipt(id=existing.public_id)
    row = Inquiry(
        type=payload.type.value,
        status=InquiryStatus.NEW.value,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        subject=payload.subject,
        message=payload.message,
        meta=payload.meta.model_dump(mode="json", exclude_defaults=True),
        idempotency_key=idempotency_key or None,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()  # the same key raced in from a double click
        replay = await replayed(db, idempotency_key)
        if replay is None:
            raise
        return replay
    return InquiryReceipt(id=row.public_id)


def _like(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _present(row: Inquiry, handler: str = "") -> InquiryAdmin:
    shown = InquiryAdmin.model_validate(row)
    shown.handled_by_name = handler
    return shown


async def _handlers(db: AsyncSession, rows: list[Inquiry]) -> dict[uuid.UUID, str]:
    ids = {row.handled_by_id for row in rows if row.handled_by_id}
    if not ids:
        return {}
    users = (
        await db.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))
    ).all()
    return {uid: (name or email) for uid, name, email in users}


async def list_inquiries(db: AsyncSession, query: InquiryQuery) -> InquiryList:
    conditions: list[Any] = []
    if query.type is not None:
        conditions.append(Inquiry.type == query.type.value)
    if query.status is not None:
        conditions.append(Inquiry.status == query.status.value)
    if query.date_from is not None:
        conditions.append(Inquiry.created_at >= datetime.combine(query.date_from, time.min, UTC))
    if query.date_to is not None:
        end = datetime.combine(query.date_to, time.min, UTC) + timedelta(days=1)
        conditions.append(Inquiry.created_at < end)
    if query.q and query.q.strip():
        pattern = _like(query.q.strip())
        conditions.append(
            or_(
                *(
                    func.lower(column).like(pattern, escape="\\")
                    for column in (
                        Inquiry.name,
                        Inquiry.email,
                        Inquiry.phone,
                        Inquiry.subject,
                        Inquiry.message,
                    )
                )
            )
        )

    def _apply(stmt: Select[Any]) -> Select[Any]:
        for condition in conditions:
            stmt = stmt.where(condition)
        return stmt

    total = int((await db.execute(_apply(select(func.count()).select_from(Inquiry)))).scalar_one())
    ordering = (
        (Inquiry.created_at.asc(), Inquiry.id.asc())
        if query.sort == "oldest"
        else (Inquiry.created_at.desc(), Inquiry.id.desc())
    )
    rows = list(
        (
            await db.execute(
                _apply(select(Inquiry))
                .order_by(*ordering)
                .offset(query.offset)
                .limit(query.page_size)
            )
        )
        .scalars()
        .all()
    )
    handlers = await _handlers(db, rows)
    return InquiryList(
        items=[
            _present(row, handlers.get(row.handled_by_id, "") if row.handled_by_id else "")
            for row in rows
        ],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=page_count(total, query.page_size),
        counts=await counts(db),
    )


async def counts(db: AsyncSession) -> InquiryCounts:
    grouped = dict(
        (await db.execute(select(Inquiry.status, func.count()).group_by(Inquiry.status))).all()
    )
    return InquiryCounts(
        new=grouped.get(InquiryStatus.NEW.value, 0),
        in_progress=grouped.get(InquiryStatus.IN_PROGRESS.value, 0),
        resolved=grouped.get(InquiryStatus.RESOLVED.value, 0),
        total=sum(grouped.values()),
    )


async def _row(db: AsyncSession, inquiry_id: uuid.UUID) -> Inquiry:
    row = await db.get(Inquiry, inquiry_id)
    if row is None:
        raise NotFoundError("Inquiry not found.")
    return row


async def get_inquiry(db: AsyncSession, inquiry_id: uuid.UUID) -> InquiryAdmin:
    row = await _row(db, inquiry_id)
    return _present(
        row, (await _handlers(db, [row])).get(row.handled_by_id, "") if row.handled_by_id else ""
    )


async def update_inquiry(
    db: AsyncSession, inquiry_id: uuid.UUID, payload: InquiryUpdate, actor: User
) -> InquiryAdmin:
    row = await _row(db, inquiry_id)
    if payload.status is not None:
        row.status = payload.status.value
    if payload.admin_note is not None:
        row.admin_note = payload.admin_note
    row.handled_by_id = actor.id
    await db.commit()
    await db.refresh(row)
    return await get_inquiry(db, inquiry_id)


async def delete_inquiry(db: AsyncSession, inquiry_id: uuid.UUID) -> None:
    """Hard delete, like other admin content: an inquiry is personal data."""
    row = await _row(db, inquiry_id)
    await db.delete(row)
    await db.commit()
