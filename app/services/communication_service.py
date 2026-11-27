"""High-scale, seller-ready Direct Communication service (Phase 19).

Design invariants:
- Strict participant & RBAC isolation:
  * Customers only access conversations where ``customer_id == user.id``.
  * Customers NEVER see ``is_internal_note=True`` messages or internal note previews.
  * Staff require dynamic RBAC ``communication`` module access.
- Zero N+1 queries:
  * Batched participant lookup + single aggregated SQL unread query.
  * O(1) keyset/cursor pagination on messages using ``(conversation_id, created_at DESC, id DESC)``.
- Resilient real-time fan-out via ``realtime_hub`` after commit (never breaks DB writes).
- Per-user send rate limit (20 messages / 10 seconds via Redis) + throttled offline notifications.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import UploadFile
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from starlette.background import BackgroundTasks

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    TooManyRequestsError,
    UnprocessableError,
)
from app.core.logging import get_logger
from app.models.communication import (
    Conversation,
    ConversationReadState,
    ConversationStatus,
    ConversationType,
    Message,
)
from app.models.notification import CustomerNotification
from app.models.order import Order
from app.models.product import Product
from app.models.user import User, UserRole
from app.schemas.common import Page, page_count
from app.schemas.communication import (
    AdminCommunicationSummaryResponse,
    AdminConversationDetailRead,
    AdminConversationUpdateRequest,
    AdminMessageCreateRequest,
    ByChannelSummary,
    ChannelGroupLiteral,
    ChannelGroupSummary,
    ChannelSummaryCount,
    ConversationCreateRequest,
    ConversationRead,
    ConversationStatusLiteral,
    ConversationTypeLiteral,
    CustomerConversationListResponse,
    CustomerMessageCreateRequest,
    MarkReadResponse,
    MessageCursorPage,
    MessageRead,
    OrderContextBrief,
    ParticipantBrief,
    ProductContextBrief,
)
from app.services import image_storage, permission_service
from app.services.realtime_hub import (
    STAFF_COMMUNICATION_CHANNEL,
    conversation_channel,
    realtime_hub,
    user_channel,
)
from app.services.redis_client import redis_client

logger = get_logger(__name__)

CHAT_RATE_LIMIT_MAX_MESSAGES = 20
CHAT_RATE_LIMIT_WINDOW_SECONDS = 10
OFFLINE_NOTIFY_THROTTLE_SECONDS = 300
MAX_MESSAGE_BODY_LEN = 2000
MAX_MESSAGES_PAGE_LIMIT = 50
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_ALL_CONVERSATION_TYPES: tuple[ConversationTypeLiteral, ...] = (
    "customer_support",
    "seller_support",
    "dropshipper_support",
    "customer_seller",
    "customer_dropshipper",
)

_CHANNEL_GROUP_TYPES: dict[str, tuple[ConversationTypeLiteral, ...]] = {
    "customer": ("customer_support",),
    "seller": ("seller_support", "customer_seller"),
    "dropshipper": ("dropshipper_support", "customer_dropshipper"),
}


def _normalize_avatar_url(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.startswith(("http://", "https://", "/")):
        return cleaned
    return f"/{cleaned}"


def _primary_external_participant_id(conv: Conversation) -> uuid.UUID | None:
    if conv.type == ConversationType.DROPSHIPPER_SUPPORT.value:
        return conv.dropshipper_id or conv.customer_id
    if conv.type == ConversationType.SELLER_SUPPORT.value:
        return conv.seller_id or conv.customer_id
    return conv.customer_id or conv.seller_id or conv.dropshipper_id


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _sanitize_body(raw: str, *, attachment_url: str | None) -> str:
    cleaned = _CONTROL_CHARS_RE.sub("", raw or "").strip()
    if len(cleaned) > MAX_MESSAGE_BODY_LEN:
        raise UnprocessableError(f"Message body must not exceed {MAX_MESSAGE_BODY_LEN} characters")
    if not cleaned and not attachment_url:
        raise UnprocessableError(
            f"Message body must be between 1 and {MAX_MESSAGE_BODY_LEN} characters"
        )
    return cleaned


def _validate_attachment_url(url: str | None) -> str | None:
    if url is None:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    if len(cleaned) > 500:
        raise UnprocessableError("Attachment URL is too long")
    if not (
        cleaned.startswith("/media/chat/")
        or cleaned.startswith("https://")
        or cleaned.startswith("http://")
    ):
        raise UnprocessableError("Attachment URL must reference an uploaded chat image")
    return cleaned


def _preview_for(body: str, attachment_url: str | None) -> str:
    if body:
        compact = " ".join(body.split())
        return compact[:240]
    if attachment_url:
        return "[Image attachment]"
    return ""


async def _enforce_send_rate_limit(user_id: uuid.UUID) -> None:
    allowed = await redis_client.check_chat_send_rate_limit(
        str(user_id),
        limit=CHAT_RATE_LIMIT_MAX_MESSAGES,
        window_seconds=CHAT_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not allowed:
        raise TooManyRequestsError(
            "You are sending messages too quickly. Please wait a few seconds."
        )


async def can_access_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    role: str,
    scope: Literal["admin", "customer"],
    conversation_id: uuid.UUID,
) -> bool:
    """Short-lived authorization check plugged into WSConnectionManager."""
    if scope == "admin":
        if role == UserRole.SUPERADMIN.value:
            return True
        if not await permission_service.role_has_admin_access(db, role):
            return False
        perms = await permission_service.get_role_permissions_map(db, role)
        return permission_service.has_module_access(perms, "communication", "read")

    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        return False
    return (
        conv.customer_id == user_id
        or conv.seller_id == user_id
        or conv.dropshipper_id == user_id
    )


async def _batch_load_users(
    db: AsyncSession,
    user_ids: set[uuid.UUID],
) -> tuple[dict[uuid.UUID, ParticipantBrief], dict[uuid.UUID, datetime | None]]:
    if not user_ids:
        return {}, {}
    rows = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
    briefs: dict[uuid.UUID, ParticipantBrief] = {}
    last_logins: dict[uuid.UUID, datetime | None] = {}
    for u in rows:
        briefs[u.id] = ParticipantBrief(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            phone=u.phone,
            role=str(u.role),
            avatar_url=_normalize_avatar_url(u.avatar_url),
        )
        last_logins[u.id] = u.last_login_at
    return briefs, last_logins


async def _unread_counts_for_conversations(
    db: AsyncSession,
    conversation_ids: list[uuid.UUID],
    viewer_id: uuid.UUID,
    *,
    include_internal_notes: bool,
) -> dict[uuid.UUID, int]:
    """Single aggregated SQL query computing unread message counts per conversation (zero N+1)."""
    if not conversation_ids:
        return {}

    read_sq = (
        select(
            ConversationReadState.conversation_id.label("conv_id"),
            ConversationReadState.last_read_at.label("last_read_at"),
        )
        .where(
            ConversationReadState.user_id == viewer_id,
            ConversationReadState.conversation_id.in_(conversation_ids),
        )
        .subquery()
    )

    conditions = [
        Message.conversation_id.in_(conversation_ids),
        or_(Message.sender_id.is_(None), Message.sender_id != viewer_id),
        or_(
            read_sq.c.last_read_at.is_(None),
            Message.created_at > read_sq.c.last_read_at,
        ),
    ]
    if not include_internal_notes:
        conditions.append(Message.is_internal_note.is_(False))

    stmt = (
        select(Message.conversation_id, func.count(Message.id))
        .outerjoin(read_sq, read_sq.c.conv_id == Message.conversation_id)
        .where(*conditions)
        .group_by(Message.conversation_id)
    )
    rows = (await db.execute(stmt)).all()
    return {conv_id: int(cnt) for conv_id, cnt in rows}


async def _customer_total_unread(db: AsyncSession, customer_id: uuid.UUID) -> int:
    """Single aggregated SQL query for total unread messages across all customer conversations."""
    read_sq = (
        select(
            ConversationReadState.conversation_id.label("conv_id"),
            ConversationReadState.last_read_at.label("last_read_at"),
        )
        .where(ConversationReadState.user_id == customer_id)
        .subquery()
    )

    stmt = (
        select(func.count(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(read_sq, read_sq.c.conv_id == Message.conversation_id)
        .where(
            Conversation.customer_id == customer_id,
            Message.is_internal_note.is_(False),
            or_(Message.sender_id.is_(None), Message.sender_id != customer_id),
            or_(
                read_sq.c.last_read_at.is_(None),
                Message.created_at > read_sq.c.last_read_at,
            ),
        )
    )
    return int((await db.scalar(stmt)) or 0)


def _serialize_conversation(
    conv: Conversation,
    users_by_id: dict[uuid.UUID, ParticipantBrief],
    unread_count: int,
    *,
    is_online: bool = False,
    last_seen_at: datetime | None = None,
) -> ConversationRead:
    return ConversationRead(
        id=conv.id,
        type=cast(ConversationTypeLiteral, conv.type),
        status=cast(ConversationStatusLiteral, conv.status),
        subject=conv.subject,
        customer_id=conv.customer_id,
        seller_id=conv.seller_id,
        dropshipper_id=conv.dropshipper_id,
        order_id=conv.order_id,
        product_id=conv.product_id,
        assigned_staff_id=conv.assigned_staff_id,
        customer=users_by_id.get(conv.customer_id) if conv.customer_id else None,
        seller=users_by_id.get(conv.seller_id) if conv.seller_id else None,
        dropshipper=users_by_id.get(conv.dropshipper_id) if conv.dropshipper_id else None,
        assigned_staff=users_by_id.get(conv.assigned_staff_id) if conv.assigned_staff_id else None,
        is_online=is_online,
        last_seen_at=last_seen_at,
        last_message_at=conv.last_message_at,
        last_message_preview=conv.last_message_preview,
        unread_count=unread_count,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


async def _serialize_conversations(
    db: AsyncSession,
    conversations: list[Conversation],
    viewer_id: uuid.UUID,
    *,
    include_internal_notes: bool,
) -> list[ConversationRead]:
    if not conversations:
        return []
    user_ids: set[uuid.UUID] = set()
    conv_ids: list[uuid.UUID] = []
    primary_ids: set[str] = set()
    for conv in conversations:
        conv_ids.append(conv.id)
        if conv.customer_id:
            user_ids.add(conv.customer_id)
        if conv.seller_id:
            user_ids.add(conv.seller_id)
        if conv.dropshipper_id:
            user_ids.add(conv.dropshipper_id)
        if conv.assigned_staff_id:
            user_ids.add(conv.assigned_staff_id)
        primary = _primary_external_participant_id(conv)
        if primary is not None:
            primary_ids.add(str(primary))

    users_by_id, last_logins = await _batch_load_users(db, user_ids)
    unread_map = await _unread_counts_for_conversations(
        db,
        conv_ids,
        viewer_id,
        include_internal_notes=include_internal_notes,
    )
    online_ids = await redis_client.get_online_user_ids(primary_ids)
    last_seen_map = await redis_client.get_last_seen_map(primary_ids)
    result: list[ConversationRead] = []
    for conv in conversations:
        primary = _primary_external_participant_id(conv)
        primary_str = str(primary) if primary is not None else None
        is_online = bool(primary_str is not None and primary_str in online_ids)
        last_seen_at = (
            last_seen_map.get(primary_str) if primary_str is not None else None
        )
        if last_seen_at is None and primary is not None:
            last_seen_at = last_logins.get(primary)
        result.append(
            _serialize_conversation(
                conv,
                users_by_id,
                unread_map.get(conv.id, 0),
                is_online=is_online,
                last_seen_at=last_seen_at,
            )
        )
    return result


async def _upsert_read_state(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    read_at: datetime | None = None,
) -> datetime:
    ts = read_at or _now_utc()
    state = await db.get(ConversationReadState, (conversation_id, user_id))
    if state is None:
        db.add(
            ConversationReadState(
                conversation_id=conversation_id,
                user_id=user_id,
                last_read_at=ts,
            )
        )
    else:
        state.last_read_at = ts
    return ts


async def _get_customer_conversation_or_404(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    customer: User,
) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.customer_id != customer.id:
        raise NotFoundError("Conversation not found")
    return conv


async def _get_conversation_or_404(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise NotFoundError("Conversation not found")
    return conv


async def _publish_message_events(
    conv: Conversation,
    msg: Message,
    sender: User,
) -> None:
    payload: dict[str, Any] = {
        "id": str(msg.id),
        "conversation_id": str(conv.id),
        "conversation_type": conv.type,
        "conversation_status": conv.status,
        "sender_id": str(sender.id),
        "sender_role": msg.sender_role,
        "sender_name": sender.full_name,
        "sender_avatar_url": _normalize_avatar_url(sender.avatar_url),
        "body": msg.body,
        "attachment_url": msg.attachment_url,
        "is_internal_note": msg.is_internal_note,
        "created_at": msg.created_at.isoformat(),
    }

    # Conversation room (WSConnectionManager also guarantees non-admin sockets never receive notes)
    await realtime_hub.publish(conversation_channel(conv.id), "message.created", payload)
    # Staff communication inbox
    await realtime_hub.publish(STAFF_COMMUNICATION_CHANNEL, "message.created", payload)

    # Direct user channels only for public messages (NEVER internal notes!)
    if not msg.is_internal_note:
        if conv.customer_id is not None:
            await realtime_hub.publish(user_channel(conv.customer_id), "message.created", payload)
        if conv.seller_id is not None:
            await realtime_hub.publish(user_channel(conv.seller_id), "message.created", payload)
        if conv.dropshipper_id is not None:
            await realtime_hub.publish(
                user_channel(conv.dropshipper_id), "message.created", payload
            )


async def _maybe_notify_offline_customer(
    db: AsyncSession,
    conv: Conversation,
    msg: Message,
    sender: User,
) -> None:
    if msg.is_internal_note or conv.customer_id is None or sender.id == conv.customer_id:
        return
    try:
        online = await redis_client.is_user_online(str(conv.customer_id))
        if online:
            return
        should_notify = await redis_client.acquire_chat_notify_throttle(
            str(conv.id),
            str(conv.customer_id),
            ttl_seconds=OFFLINE_NOTIFY_THROTTLE_SECONDS,
        )
        if not should_notify:
            return

        preview = _preview_for(msg.body, msg.attachment_url)
        notif = CustomerNotification(
            user_id=conv.customer_id,
            order_id=conv.order_id,
            type="support_message",
            title="New reply from Support",
            message=preview[:1000] if preview else "Support replied to your conversation.",
            is_read=False,
            language="en",
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)

        unread_notifs = int(
            (
                await db.scalar(
                    select(func.count(CustomerNotification.id)).where(
                        CustomerNotification.user_id == conv.customer_id,
                        CustomerNotification.is_read.is_(False),
                    )
                )
            )
            or 0
        )
        await realtime_hub.publish(
            user_channel(conv.customer_id),
            "notification.created",
            {
                "id": str(notif.id),
                "type": notif.type,
                "title": notif.title,
                "message": notif.message,
                "order_id": str(notif.order_id) if notif.order_id else None,
                "created_at": notif.created_at.isoformat(),
                "unread_count": unread_notifs,
            },
        )
        await realtime_hub.publish(
            user_channel(conv.customer_id),
            "notification.unread",
            {"unread_count": unread_notifs},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "communication_offline_notify_failed",
            conversation_id=str(conv.id),
            error=str(exc),
        )


async def _dispatch_chat_push_and_fallback(
    db: AsyncSession,
    conv: Conversation,
    msg: Message,
    sender: User,
    background: BackgroundTasks | None,
) -> None:
    from app.services import push_service, telegram_notify

    excerpt = _preview_for(msg.body, msg.attachment_url) or "New message"
    sender_role = str(sender.role)

    if sender_role in ("customer", "seller"):
        if push_service.is_configured():
            staff_ids = await push_service.staff_ids_with_module_read(
                db,
                "communication",
                exclude_user_id=sender.id,
            )
            if staff_ids:
                payload = push_service.build_push_payload(
                    title=f"New message from {sender.full_name}",
                    body=excerpt,
                    url=f"/admin/communication?id={conv.id}",
                    tag=f"implesia-chat-{conv.id}",
                    scope="admin",
                    conversation_id=str(conv.id),
                    can_quick_reply=True,
                )
                push_service.schedule_push_to_users(background, staff_ids, "admin", payload)

        if sender_role == "customer":
            order_number: str | None = None
            if conv.order_id is not None:
                order_number = await db.scalar(
                    select(Order.number).where(Order.id == conv.order_id)
                )
            telegram_notify.schedule_unanswered_chat_fallback(
                background,
                conversation_id=conv.id,
                message_created_at=msg.created_at,
                customer_name=sender.full_name,
                customer_phone=sender.phone,
                order_number=order_number,
                excerpt=excerpt,
            )
    elif (
        not msg.is_internal_note and conv.customer_id is not None and sender.id != conv.customer_id
    ):
        if push_service.is_configured():
            payload = push_service.build_push_payload(
                title=f"Reply from {sender.full_name or 'Implesia Support'}",
                body=excerpt,
                url=f"/dashboard/messages?id={conv.id}",
                tag=f"implesia-chat-{conv.id}",
                scope="customer",
                conversation_id=str(conv.id),
                can_quick_reply=True,
            )
            push_service.schedule_push_to_users(background, [conv.customer_id], "customer", payload)


async def _create_message_and_commit(
    db: AsyncSession,
    conv: Conversation,
    sender: User,
    *,
    raw_body: str,
    raw_attachment_url: str | None,
    is_internal_note: bool,
    reopen_if_customer: bool,
    background: BackgroundTasks | None = None,
) -> MessageRead:
    await _enforce_send_rate_limit(sender.id)

    attachment_url = _validate_attachment_url(raw_attachment_url)
    body = _sanitize_body(raw_body, attachment_url=attachment_url)
    now = _now_utc()

    msg = Message(
        conversation_id=conv.id,
        sender_id=sender.id,
        sender_role=str(sender.role),
        body=body,
        attachment_url=attachment_url,
        is_internal_note=is_internal_note,
        created_at=now,
    )
    db.add(msg)

    # CRITICAL PRIVACY: Internal notes must NEVER leak into conversation.last_message_preview
    # (which is visible to the customer on their conversation list).
    if not is_internal_note:
        conv.last_message_at = now
        conv.last_message_preview = _preview_for(body, attachment_url)
    elif conv.last_message_at is None:
        conv.last_message_at = now

    if reopen_if_customer and conv.status in {
        ConversationStatus.RESOLVED.value,
        ConversationStatus.CLOSED.value,
    }:
        conv.status = ConversationStatus.OPEN.value

    await _upsert_read_state(db, conv.id, sender.id, read_at=now)
    await db.commit()
    await db.refresh(msg)
    await db.refresh(conv)

    await _publish_message_events(conv, msg, sender)
    await _maybe_notify_offline_customer(db, conv, msg, sender)
    await _dispatch_chat_push_and_fallback(db, conv, msg, sender, background)

    return MessageRead(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        sender_role=msg.sender_role,
        sender_name=sender.full_name,
        sender_avatar_url=_normalize_avatar_url(sender.avatar_url),
        body=msg.body,
        attachment_url=msg.attachment_url,
        is_internal_note=msg.is_internal_note,
        created_at=msg.created_at,
    )


async def _list_messages_cursor(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    include_internal_notes: bool,
    before_created_at: datetime | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 30,
) -> MessageCursorPage:
    clamped_limit = max(1, min(limit, MAX_MESSAGES_PAGE_LIMIT))
    conditions: list[Any] = [Message.conversation_id == conversation_id]
    if not include_internal_notes:
        conditions.append(Message.is_internal_note.is_(False))

    if before_created_at is not None:
        cursor_ts = (
            before_created_at
            if before_created_at.tzinfo is not None
            else before_created_at.replace(tzinfo=UTC)
        )
        if before_id is not None:
            conditions.append(
                or_(
                    Message.created_at < cursor_ts,
                    and_(Message.created_at == cursor_ts, Message.id < before_id),
                )
            )
        else:
            conditions.append(Message.created_at < cursor_ts)

    stmt = (
        select(Message)
        .where(*conditions)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(clamped_limit + 1)
    )
    rows = list((await db.scalars(stmt)).all())
    has_more = len(rows) > clamped_limit
    page_rows = rows[:clamped_limit]

    sender_ids = {m.sender_id for m in page_rows if m.sender_id is not None}
    sender_info: dict[uuid.UUID, tuple[str, str | None]] = {}
    if sender_ids:
        user_rows = (
            await db.execute(
                select(User.id, User.full_name, User.avatar_url).where(User.id.in_(sender_ids))
            )
        ).all()
        sender_info = {
            uid: (str(name), _normalize_avatar_url(avatar))
            for uid, name, avatar in user_rows
        }

    items = [
        MessageRead(
            id=m.id,
            conversation_id=m.conversation_id,
            sender_id=m.sender_id,
            sender_role=m.sender_role,
            sender_name=sender_info[m.sender_id][0]
            if m.sender_id and m.sender_id in sender_info
            else None,
            sender_avatar_url=sender_info[m.sender_id][1]
            if m.sender_id and m.sender_id in sender_info
            else None,
            body=m.body,
            attachment_url=m.attachment_url,
            is_internal_note=m.is_internal_note,
            created_at=m.created_at,
        )
        for m in page_rows
    ]

    next_before_created_at = page_rows[-1].created_at if has_more and page_rows else None
    next_before_id = page_rows[-1].id if has_more and page_rows else None

    return MessageCursorPage(
        items=items,
        has_more=has_more,
        next_before_created_at=next_before_created_at,
        next_before_id=next_before_id,
    )


async def upload_chat_attachment(file: UploadFile) -> str:
    data = await image_storage.read_image(file)
    return image_storage.store_image(data, folder="chat")


# ---------------------------------------------------------------------------
# Customer API operations
# ---------------------------------------------------------------------------


async def list_customer_conversations(
    db: AsyncSession,
    customer: User,
    *,
    page: int = 1,
    page_size: int = 20,
) -> CustomerConversationListResponse:
    total = int(
        (
            await db.scalar(
                select(func.count(Conversation.id)).where(Conversation.customer_id == customer.id)
            )
        )
        or 0
    )
    offset = (page - 1) * page_size
    stmt = (
        select(Conversation)
        .where(Conversation.customer_id == customer.id)
        .order_by(
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
            Conversation.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
    )
    rows = list((await db.scalars(stmt)).all())
    items = await _serialize_conversations(
        db,
        rows,
        customer.id,
        include_internal_notes=False,
    )
    total_unread = await _customer_total_unread(db, customer.id)

    return CustomerConversationListResponse(
        items=items,
        total=total,
        total_unread=total_unread,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def start_or_reuse_customer_conversation(
    db: AsyncSession,
    customer: User,
    payload: ConversationCreateRequest,
) -> ConversationRead:
    if payload.order_id is not None:
        order = await db.get(Order, payload.order_id)
        if order is None or order.user_id != customer.id:
            raise NotFoundError("Order not found")

    if payload.product_id is not None:
        product = await db.get(Product, payload.product_id)
        if product is None:
            raise NotFoundError("Product not found")

    # Reuse an active open/pending customer_support conversation for the exact same context.
    reuse_filters = [
        Conversation.type == ConversationType.CUSTOMER_SUPPORT.value,
        Conversation.customer_id == customer.id,
        Conversation.status.in_([ConversationStatus.OPEN.value, ConversationStatus.PENDING.value]),
        Conversation.order_id == payload.order_id
        if payload.order_id is not None
        else Conversation.order_id.is_(None),
        Conversation.product_id == payload.product_id
        if payload.product_id is not None
        else Conversation.product_id.is_(None),
    ]
    existing = await db.scalar(
        select(Conversation)
        .where(*reuse_filters)
        .order_by(
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
            Conversation.id.desc(),
        )
        .limit(1)
    )

    conv = existing
    if conv is None:
        now = _now_utc()
        conv = Conversation(
            type=ConversationType.CUSTOMER_SUPPORT.value,
            customer_id=customer.id,
            order_id=payload.order_id,
            product_id=payload.product_id,
            subject=payload.subject or "Support Conversation",
            status=ConversationStatus.OPEN.value,
            last_message_at=now,
            last_message_preview="",
        )
        db.add(conv)
        await db.flush()
        await _upsert_read_state(db, conv.id, customer.id, read_at=now)
        await db.commit()
        await db.refresh(conv)

    if payload.initial_message:
        await _create_message_and_commit(
            db,
            conv,
            customer,
            raw_body=payload.initial_message,
            raw_attachment_url=None,
            is_internal_note=False,
            reopen_if_customer=True,
        )
        await db.refresh(conv)

    serialized = await _serialize_conversations(
        db,
        [conv],
        customer.id,
        include_internal_notes=False,
    )
    return serialized[0]


async def list_customer_messages(
    db: AsyncSession,
    customer: User,
    conversation_id: uuid.UUID,
    *,
    before_created_at: datetime | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 30,
) -> MessageCursorPage:
    conv = await _get_customer_conversation_or_404(db, conversation_id, customer)
    return await _list_messages_cursor(
        db,
        conv.id,
        include_internal_notes=False,
        before_created_at=before_created_at,
        before_id=before_id,
        limit=limit,
    )


async def send_customer_message(
    db: AsyncSession,
    customer: User,
    conversation_id: uuid.UUID,
    payload: CustomerMessageCreateRequest,
    *,
    background: BackgroundTasks | None = None,
) -> MessageRead:
    conv = await _get_customer_conversation_or_404(db, conversation_id, customer)
    return await _create_message_and_commit(
        db,
        conv,
        customer,
        raw_body=payload.body,
        raw_attachment_url=payload.attachment_url,
        is_internal_note=False,
        reopen_if_customer=True,
        background=background,
    )


async def upload_customer_attachment(
    db: AsyncSession,
    customer: User,
    conversation_id: uuid.UUID,
    file: UploadFile,
) -> str:
    await _get_customer_conversation_or_404(db, conversation_id, customer)
    return await upload_chat_attachment(file)


async def mark_customer_conversation_read(
    db: AsyncSession,
    customer: User,
    conversation_id: uuid.UUID,
) -> MarkReadResponse:
    conv = await _get_customer_conversation_or_404(db, conversation_id, customer)
    ts = await _upsert_read_state(db, conv.id, customer.id)
    await db.commit()
    return MarkReadResponse(conversation_id=conv.id, last_read_at=ts, unread_count=0)


# ---------------------------------------------------------------------------
# Admin API operations
# ---------------------------------------------------------------------------


async def get_admin_summary(
    db: AsyncSession,
    staff: User,
) -> AdminCommunicationSummaryResponse:
    # Query 1: Aggregated status & unassigned counts grouped by conversation type.
    status_stmt = select(
        Conversation.type,
        Conversation.status,
        func.count(Conversation.id),
        func.sum(case((Conversation.assigned_staff_id.is_(None), 1), else_=0)),
    ).group_by(Conversation.type, Conversation.status)
    status_rows = (await db.execute(status_stmt)).all()

    buckets: dict[str, ChannelSummaryCount] = {
        t: ChannelSummaryCount(type=t) for t in _ALL_CONVERSATION_TYPES
    }
    for conv_type, conv_status, cnt_raw, unassigned_raw in status_rows:
        bucket = buckets.get(str(conv_type))
        if bucket is None:
            continue
        cnt = int(cnt_raw or 0)
        unassigned = int(unassigned_raw or 0)
        bucket.total += cnt
        bucket.unassigned += unassigned
        if conv_status == ConversationStatus.OPEN.value:
            bucket.open += cnt
        elif conv_status == ConversationStatus.PENDING.value:
            bucket.pending += cnt
        elif conv_status == ConversationStatus.RESOLVED.value:
            bucket.resolved += cnt
        elif conv_status == ConversationStatus.CLOSED.value:
            bucket.closed += cnt

    # Query 2: Single aggregated unread query across all conversations for this staff user.
    read_sq = (
        select(
            ConversationReadState.conversation_id.label("conv_id"),
            ConversationReadState.last_read_at.label("last_read_at"),
        )
        .where(ConversationReadState.user_id == staff.id)
        .subquery()
    )
    unread_stmt = (
        select(
            Conversation.type,
            Message.conversation_id,
            func.count(Message.id),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(read_sq, read_sq.c.conv_id == Message.conversation_id)
        .where(
            or_(Message.sender_id.is_(None), Message.sender_id != staff.id),
            or_(
                read_sq.c.last_read_at.is_(None),
                Message.created_at > read_sq.c.last_read_at,
            ),
        )
        .group_by(Conversation.type, Message.conversation_id)
    )
    unread_rows = (await db.execute(unread_stmt)).all()

    total_unread_messages = 0
    unread_messages_by_type: dict[str, int] = dict.fromkeys(_ALL_CONVERSATION_TYPES, 0)
    for conv_type, _conv_id, unread_cnt_raw in unread_rows:
        unread_cnt = int(unread_cnt_raw or 0)
        if unread_cnt <= 0:
            continue
        total_unread_messages += unread_cnt
        key = str(conv_type)
        bucket = buckets.get(key)
        if bucket is not None:
            bucket.unread_conversations += 1
            unread_messages_by_type[key] = unread_messages_by_type.get(key, 0) + unread_cnt

    by_type = [buckets[t] for t in _ALL_CONVERSATION_TYPES]

    def _channel_summary(types: tuple[ConversationTypeLiteral, ...]) -> ChannelGroupSummary:
        return ChannelGroupSummary(
            open_count=sum(buckets[t].open for t in types),
            unread_conversations=sum(buckets[t].unread_conversations for t in types),
            total_unread_messages=sum(unread_messages_by_type[t] for t in types),
        )

    by_channel = ByChannelSummary(
        customer=_channel_summary(_CHANNEL_GROUP_TYPES["customer"]),
        seller=_channel_summary(_CHANNEL_GROUP_TYPES["seller"]),
        dropshipper=_channel_summary(_CHANNEL_GROUP_TYPES["dropshipper"]),
    )

    return AdminCommunicationSummaryResponse(
        open_count=sum(b.open for b in by_type),
        pending_count=sum(b.pending for b in by_type),
        resolved_count=sum(b.resolved for b in by_type),
        closed_count=sum(b.closed for b in by_type),
        unassigned_count=sum(b.unassigned for b in by_type),
        unread_conversations_count=sum(b.unread_conversations for b in by_type),
        total_unread_messages=total_unread_messages,
        by_type=by_type,
        by_channel=by_channel,
    )


async def list_admin_conversations(
    db: AsyncSession,
    staff: User,
    *,
    conv_type: ConversationTypeLiteral | None = None,
    channel_group: ChannelGroupLiteral | None = None,
    status: ConversationStatusLiteral | None = None,
    assigned: str | None = None,
    assigned_staff_id: uuid.UUID | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[ConversationRead]:
    customer_alias = aliased(User)
    seller_alias = aliased(User)
    dropshipper_alias = aliased(User)

    filters: list[Any] = []
    if conv_type is not None:
        filters.append(Conversation.type == conv_type)
    if channel_group is not None and channel_group != "all":
        group_types = _CHANNEL_GROUP_TYPES.get(channel_group)
        if group_types:
            filters.append(Conversation.type.in_(group_types))
    if status is not None:
        filters.append(Conversation.status == status)
    if assigned_staff_id is not None:
        filters.append(Conversation.assigned_staff_id == assigned_staff_id)
    elif assigned is not None:
        cleaned_assigned = assigned.strip().lower()
        if cleaned_assigned == "unassigned":
            filters.append(Conversation.assigned_staff_id.is_(None))
        elif cleaned_assigned == "me":
            filters.append(Conversation.assigned_staff_id == staff.id)
        elif cleaned_assigned == "assigned":
            filters.append(Conversation.assigned_staff_id.is_not(None))
        else:
            try:
                filters.append(Conversation.assigned_staff_id == uuid.UUID(cleaned_assigned))
            except ValueError as exc:
                raise UnprocessableError("Invalid assigned filter value") from exc

    search_term = (q or "").strip()
    if search_term:
        pattern = f"%{search_term}%"
        filters.append(
            or_(
                Conversation.subject.ilike(pattern),
                Conversation.last_message_preview.ilike(pattern),
                customer_alias.full_name.ilike(pattern),
                customer_alias.phone.ilike(pattern),
                customer_alias.email.ilike(pattern),
                seller_alias.full_name.ilike(pattern),
                seller_alias.phone.ilike(pattern),
                dropshipper_alias.full_name.ilike(pattern),
                dropshipper_alias.phone.ilike(pattern),
            )
        )

    base = (
        select(Conversation)
        .outerjoin(customer_alias, Conversation.customer_id == customer_alias.id)
        .outerjoin(seller_alias, Conversation.seller_id == seller_alias.id)
        .outerjoin(dropshipper_alias, Conversation.dropshipper_id == dropshipper_alias.id)
        .where(*filters)
    )
    count_stmt = (
        select(func.count(Conversation.id))
        .outerjoin(customer_alias, Conversation.customer_id == customer_alias.id)
        .outerjoin(seller_alias, Conversation.seller_id == seller_alias.id)
        .outerjoin(dropshipper_alias, Conversation.dropshipper_id == dropshipper_alias.id)
        .where(*filters)
    )

    total = int((await db.scalar(count_stmt)) or 0)
    offset = (page - 1) * page_size
    rows = list(
        (
            await db.scalars(
                base.order_by(
                    func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
                    Conversation.id.desc(),
                )
                .offset(offset)
                .limit(page_size)
            )
        ).all()
    )
    items = await _serialize_conversations(
        db,
        rows,
        staff.id,
        include_internal_notes=True,
    )
    return Page(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def get_admin_conversation_detail(
    db: AsyncSession,
    staff: User,
    conversation_id: uuid.UUID,
) -> AdminConversationDetailRead:
    conv = await _get_conversation_or_404(db, conversation_id)
    base_list = await _serialize_conversations(
        db,
        [conv],
        staff.id,
        include_internal_notes=True,
    )
    base = base_list[0]

    order_brief: OrderContextBrief | None = None
    if conv.order_id is not None:
        order_row = await db.get(Order, conv.order_id)
        if order_row is not None:
            order_brief = OrderContextBrief.model_validate(order_row)

    product_brief: ProductContextBrief | None = None
    if conv.product_id is not None:
        product_row = await db.get(Product, conv.product_id)
        if product_row is not None:
            product_brief = ProductContextBrief.model_validate(product_row)

    recent_orders: list[OrderContextBrief] = []
    customer_is_online = False
    if conv.customer_id is not None:
        recent_rows = (
            await db.scalars(
                select(Order)
                .where(Order.user_id == conv.customer_id)
                .order_by(Order.created_at.desc())
                .limit(5)
            )
        ).all()
        recent_orders = [OrderContextBrief.model_validate(o) for o in recent_rows]
        customer_is_online = await redis_client.is_user_online(str(conv.customer_id))

    return AdminConversationDetailRead(
        **base.model_dump(),
        order=order_brief,
        product=product_brief,
        recent_orders=recent_orders,
        customer_is_online=customer_is_online,
    )


async def list_admin_messages(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    before_created_at: datetime | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 30,
) -> MessageCursorPage:
    conv = await _get_conversation_or_404(db, conversation_id)
    return await _list_messages_cursor(
        db,
        conv.id,
        include_internal_notes=True,
        before_created_at=before_created_at,
        before_id=before_id,
        limit=limit,
    )


async def send_admin_message(
    db: AsyncSession,
    staff: User,
    conversation_id: uuid.UUID,
    payload: AdminMessageCreateRequest,
    *,
    background: BackgroundTasks | None = None,
) -> MessageRead:
    conv = await _get_conversation_or_404(db, conversation_id)
    return await _create_message_and_commit(
        db,
        conv,
        staff,
        raw_body=payload.body,
        raw_attachment_url=payload.attachment_url,
        is_internal_note=payload.is_internal_note,
        reopen_if_customer=False,
        background=background,
    )


async def upload_admin_attachment(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    file: UploadFile,
) -> str:
    await _get_conversation_or_404(db, conversation_id)
    return await upload_chat_attachment(file)


async def update_admin_conversation(
    db: AsyncSession,
    staff: User,
    conversation_id: uuid.UUID,
    payload: AdminConversationUpdateRequest,
) -> ConversationRead:
    conv = await _get_conversation_or_404(db, conversation_id)
    changed = False

    if "status" in payload.model_fields_set and payload.status is not None:
        conv.status = payload.status
        changed = True

    if "assigned_staff_id" in payload.model_fields_set:
        if payload.assigned_staff_id is None:
            conv.assigned_staff_id = None
            changed = True
        else:
            assignee = await db.get(User, payload.assigned_staff_id)
            if assignee is None or not assignee.is_active:
                raise NotFoundError("Assigned staff user not found")
            if not await permission_service.role_has_admin_access(db, assignee.role):
                raise PermissionDeniedError("Cannot assign a conversation to a non-staff user")
            conv.assigned_staff_id = assignee.id
            changed = True

    if changed:
        await db.commit()
        await db.refresh(conv)
        await realtime_hub.publish(
            STAFF_COMMUNICATION_CHANNEL,
            "conversation.updated",
            {
                "conversation_id": str(conv.id),
                "status": conv.status,
                "assigned_staff_id": str(conv.assigned_staff_id)
                if conv.assigned_staff_id
                else None,
                "updated_by": str(staff.id),
            },
        )

    serialized = await _serialize_conversations(
        db,
        [conv],
        staff.id,
        include_internal_notes=True,
    )
    return serialized[0]


async def mark_admin_conversation_read(
    db: AsyncSession,
    staff: User,
    conversation_id: uuid.UUID,
) -> MarkReadResponse:
    conv = await _get_conversation_or_404(db, conversation_id)
    ts = await _upsert_read_state(db, conv.id, staff.id)
    await db.commit()
    return MarkReadResponse(conversation_id=conv.id, last_read_at=ts, unread_count=0)
