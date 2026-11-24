import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VapidPublicKeyResponse(BaseModel):
    enabled: bool
    public_key: str


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=256)
    auth: str = Field(min_length=8, max_length=128)


class PushSubscriptionUpsertRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1024)
    keys: PushSubscriptionKeys
    user_agent: str | None = Field(default=None, max_length=256)


class PushSubscriptionDeleteRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1024)


class PushSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    scope: str
    endpoint: str
    user_agent: str | None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
