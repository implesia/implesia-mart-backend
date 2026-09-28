from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.dashboard import DashboardSummary


async def summary(db: AsyncSession) -> DashboardSummary:
    total = await db.scalar(select(func.count()).select_from(User)) or 0
    active = (
        await db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
    )
    return DashboardSummary(users_total=int(total), users_active=int(active))
