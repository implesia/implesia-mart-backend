from pydantic import BaseModel


class DashboardSummary(BaseModel):
    users_total: int
    users_active: int
