import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent

# A key containing any of these is dropped, including nested objects.
_FORBIDDEN_KEY = ("password", "token", "secret", "authorization", "cookie")
_JWT = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")


def redact_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    """Return a JSON object that cannot carry a password, token, or secret."""
    if not isinstance(value, dict):
        return {}
    return _clean_object(value)


async def record(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Stage an audit row. The caller commits it with the change it describes."""
    db.add(
        AuditEvent(
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            event_metadata=redact_metadata(metadata),
        )
    )


async def list_events(
    db: AsyncSession,
    offset: int,
    limit: int,
    *,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> tuple[list[AuditEvent], int]:
    filters = []
    if action:
        filters.append(AuditEvent.action == action)
    if target_type:
        filters.append(AuditEvent.target_type == target_type)
    if target_id:
        filters.append(AuditEvent.target_id == target_id)
    if actor_user_id is not None:
        filters.append(AuditEvent.actor_user_id == actor_user_id)

    total = await db.scalar(select(func.count()).select_from(AuditEvent).where(*filters)) or 0
    result = await db.execute(
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total)


def _forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _FORBIDDEN_KEY)


def _clean_object(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or _forbidden(key):
            continue
        kept = _clean_value(item)
        if kept is _DROP:
            continue
        cleaned[key] = kept
    return cleaned


class _Drop:
    pass


_DROP = _Drop()


def _clean_value(value: object) -> Any:
    if isinstance(value, dict):
        return _clean_object(value)
    if isinstance(value, list):
        return [item for item in (_clean_value(entry) for entry in value) if item is not _DROP]
    if isinstance(value, str):
        if _JWT.fullmatch(value) or value.lower().startswith("bearer "):
            return _DROP
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    return str(value)
