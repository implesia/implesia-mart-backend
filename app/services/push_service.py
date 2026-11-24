"""100% Free W3C Web Push (VAPID) subscription store and non-blocking dispatcher."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.background import BackgroundTasks

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.services import permission_service

logger = get_logger("webpush")

PushScope = Literal["admin", "customer"]
MAX_DEVICES_PER_USER_SCOPE = 10
_SEND_CONCURRENCY = 10
_HTTP_TIMEOUT_SECONDS = 8

# Keep references to fire-and-forget tasks so GC never cancels them prematurely.
_background_tasks: set[asyncio.Task[Any]] = set()


def is_configured() -> bool:
    return bool(
        settings.vapid_public_key.strip() and settings.vapid_private_key.get_secret_value().strip()
    )


def public_key() -> str:
    return settings.vapid_public_key.strip()


async def upsert_subscription(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    scope: PushScope,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None = None,
) -> PushSubscription:
    clean_endpoint = endpoint.strip()
    clean_ua = user_agent.strip()[:256] if user_agent else None

    existing = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == clean_endpoint)
    )
    if existing is not None:
        existing.user_id = user_id
        existing.scope = scope
        existing.p256dh = p256dh.strip()
        existing.auth = auth.strip()
        if clean_ua is not None:
            existing.user_agent = clean_ua
        existing.updated_at = datetime.now(UTC)
        sub = existing
    else:
        sub = PushSubscription(
            user_id=user_id,
            scope=scope,
            endpoint=clean_endpoint,
            p256dh=p256dh.strip(),
            auth=auth.strip(),
            user_agent=clean_ua,
        )
        db.add(sub)
        await db.flush()

    # Enforce cap of MAX_DEVICES_PER_USER_SCOPE active devices per (user_id, scope),
    # evicting the oldest entries.
    rows = list(
        (
            await db.scalars(
                select(PushSubscription)
                .where(
                    PushSubscription.user_id == user_id,
                    PushSubscription.scope == scope,
                )
                .order_by(PushSubscription.updated_at.desc(), PushSubscription.created_at.desc())
            )
        ).all()
    )
    if len(rows) > MAX_DEVICES_PER_USER_SCOPE:
        # Always keep the newly inserted/updated subscription (`sub.id`) even on timestamp ties.
        other_ids = [row.id for row in rows if row.id != sub.id]
        stale_ids = other_ids[MAX_DEVICES_PER_USER_SCOPE - 1 :]
        if stale_ids:
            await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(stale_ids)))

    await db.commit()
    await db.refresh(sub)
    return sub


async def delete_subscription(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    endpoint: str,
) -> bool:
    clean_endpoint = endpoint.strip()
    sub = await db.scalar(
        select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == clean_endpoint,
        )
    )
    if sub is None:
        return False
    await db.delete(sub)
    await db.commit()
    return True


async def staff_ids_with_module_read(
    db: AsyncSession,
    module_key: str,
    *,
    exclude_user_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Return IDs of active staff users whose role currently grants read access to module_key."""
    staff_roles = await permission_service.get_admin_role_slugs(db)
    if not staff_roles:
        return []
    users = list(
        (
            await db.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    User.role.in_(tuple(staff_roles)),
                )
            )
        ).all()
    )
    role_allows: dict[str, bool] = {}
    recipients: list[uuid.UUID] = []
    for user in users:
        if exclude_user_id is not None and user.id == exclude_user_id:
            continue
        role_key = str(user.role)
        allowed = role_allows.get(role_key)
        if allowed is None:
            perms = await permission_service.get_role_permissions_map(db, role_key)
            allowed = permission_service.has_module_access(perms, module_key, "read")
            role_allows[role_key] = allowed
        if allowed:
            recipients.append(user.id)
    return recipients


def build_push_payload(
    *,
    title: str,
    body: str,
    url: str,
    tag: str,
    scope: PushScope,
    conversation_id: str | None = None,
    can_quick_reply: bool = False,
    icon: str = "/images/common/logo.png",
    badge: str = "/favicon.ico",
) -> dict[str, Any]:
    return {
        "title": title[:120],
        "body": body[:240],
        "url": url,
        "tag": tag,
        "conversationId": conversation_id,
        "scope": scope,
        "canQuickReply": can_quick_reply,
        "icon": icon,
        "badge": badge,
    }


def _deliver_single(subscription_info: dict[str, Any], payload_json: str) -> None:
    webpush(
        subscription_info=subscription_info,
        data=payload_json,
        vapid_private_key=settings.vapid_private_key.get_secret_value().strip(),
        vapid_claims={"sub": settings.vapid_subject.strip() or "mailto:support@implesia.com"},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )


async def send_push_to_users(
    user_ids: Iterable[uuid.UUID],
    scope: PushScope,
    payload: dict[str, Any],
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Send encrypted Web Push notifications to all active devices for user_ids + scope.

    Runs safely outside the HTTP request lifecycle with bounded concurrency and
    automatic cleanup of expired (404/410 Gone) endpoints.
    """
    if not is_configured():
        return 0
    unique_ids = list({uid for uid in user_ids if uid is not None})
    if not unique_ids:
        return 0

    async with session_factory() as db:
        subs = list(
            (
                await db.scalars(
                    select(PushSubscription).where(
                        PushSubscription.user_id.in_(unique_ids),
                        PushSubscription.scope == scope,
                    )
                )
            ).all()
        )
        if not subs:
            return 0

        payload_json = json.dumps(payload, separators=(",", ":"))
        sem = asyncio.Semaphore(_SEND_CONCURRENCY)
        dead_ids: list[uuid.UUID] = []
        sent_ids: list[uuid.UUID] = []

        async def _send_one(sub: PushSubscription) -> None:
            info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            async with sem:
                try:
                    await asyncio.to_thread(_deliver_single, info, payload_json)
                    sent_ids.append(sub.id)
                except WebPushException as exc:
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    if status_code in (404, 410):
                        dead_ids.append(sub.id)
                        logger.info(
                            "webpush_expired_removed",
                            scope=scope,
                            status_code=status_code,
                        )
                    else:
                        logger.warning(
                            "webpush_delivery_failed",
                            scope=scope,
                            status_code=status_code,
                        )
                except Exception:
                    logger.warning("webpush_delivery_error", scope=scope)

        await asyncio.gather(*(_send_one(sub) for sub in subs))

        changed = False
        if dead_ids:
            await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(dead_ids)))
            changed = True
        if sent_ids:
            now = datetime.now(UTC)
            for sub in subs:
                if sub.id in sent_ids:
                    sub.last_used_at = now
            changed = True
        if changed:
            await db.commit()

        return len(sent_ids)


def schedule_push_to_users(
    background: BackgroundTasks | None,
    user_ids: Iterable[uuid.UUID],
    scope: PushScope,
    payload: dict[str, Any],
) -> None:
    """Queue Web Push dispatch without blocking the HTTP response."""
    if not is_configured():
        return
    unique_ids = list({uid for uid in user_ids if uid is not None})
    if not unique_ids:
        return
    if background is not None:
        background.add_task(send_push_to_users, unique_ids, scope, payload)
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(send_push_to_users(unique_ids, scope, payload))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
