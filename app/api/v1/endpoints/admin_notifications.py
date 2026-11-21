"""Admin notification moderation. Only editors/superadmins can delete customer notifications."""

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_module_access
from app.core.exceptions import NotFoundError
from app.services import notification_service

router = APIRouter(
    dependencies=[Depends(no_store), Depends(require_module_access("orders", "write"))]
)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_notification_admin(
    db: DbSession,
    notification_id: uuid.UUID,
) -> None:
    ok = await notification_service.admin_delete_notification(db, notification_id)
    if not ok:
        raise NotFoundError("Notification not found")
