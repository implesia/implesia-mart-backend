"""Pydantic v2 schemas for the Direct Communication Engine (Phase 19)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConversationTypeLiteral = Literal[
    "customer_support",
    "seller_support",
    "dropshipper_support",
    "customer_seller",
    "customer_dropshipper",
]
ChannelGroupLiteral = Literal["all", "customer", "seller", "dropshipper"]
ConversationStatusLiteral = Literal["open", "pending", "resolved", "closed"]


class ParticipantBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str | None = None
    phone: str | None = None
    role: str
    avatar_url: str | None = None


class OrderContextBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    status: str
    total: int
    payment_method: str
    created_at: datetime


class ProductContextBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    price: int
    image_src: str


class ConversationCreateRequest(BaseModel):
    order_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    subject: str = Field(default="", max_length=200)
    initial_message: str | None = Field(default=None, max_length=2000)

    @field_validator("subject")
    @classmethod
    def _clean_subject(cls, v: str) -> str:
        return " ".join(v.strip().split())[:200]

    @field_validator("initial_message")
    @classmethod
    def _clean_initial_message(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None


class CustomerMessageCreateRequest(BaseModel):
    body: str = Field(default="", max_length=2000)
    attachment_url: str | None = Field(default=None, max_length=500)


class AdminMessageCreateRequest(BaseModel):
    body: str = Field(default="", max_length=2000)
    attachment_url: str | None = Field(default=None, max_length=500)
    is_internal_note: bool = False


class AdminConversationUpdateRequest(BaseModel):
    status: ConversationStatusLiteral | None = None
    assigned_staff_id: uuid.UUID | None = None


class ConversationRead(BaseModel):
    id: uuid.UUID
    type: ConversationTypeLiteral
    status: ConversationStatusLiteral
    subject: str
    customer_id: uuid.UUID | None = None
    seller_id: uuid.UUID | None = None
    dropshipper_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    assigned_staff_id: uuid.UUID | None = None
    customer: ParticipantBrief | None = None
    seller: ParticipantBrief | None = None
    dropshipper: ParticipantBrief | None = None
    assigned_staff: ParticipantBrief | None = None
    is_online: bool = False
    last_seen_at: datetime | None = None
    last_message_at: datetime | None = None
    last_message_preview: str = ""
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime


class AdminConversationDetailRead(ConversationRead):
    order: OrderContextBrief | None = None
    product: ProductContextBrief | None = None
    recent_orders: list[OrderContextBrief] = Field(default_factory=list)
    customer_is_online: bool = False


class CustomerConversationListResponse(BaseModel):
    items: list[ConversationRead]
    total: int
    total_unread: int
    page: int
    page_size: int
    pages: int


class MessageRead(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID | None = None
    sender_role: str
    sender_name: str | None = None
    sender_avatar_url: str | None = None
    body: str
    attachment_url: str | None = None
    is_internal_note: bool = False
    created_at: datetime


class MessageCursorPage(BaseModel):
    items: list[MessageRead]
    has_more: bool
    next_before_created_at: datetime | None = None
    next_before_id: uuid.UUID | None = None


class AttachmentUploadResponse(BaseModel):
    url: str


class MarkReadResponse(BaseModel):
    conversation_id: uuid.UUID
    last_read_at: datetime
    unread_count: int = 0


class ChannelSummaryCount(BaseModel):
    type: ConversationTypeLiteral
    open: int = 0
    pending: int = 0
    resolved: int = 0
    closed: int = 0
    unassigned: int = 0
    unread_conversations: int = 0
    total: int = 0


class ChannelGroupSummary(BaseModel):
    open_count: int = 0
    unread_conversations: int = 0
    total_unread_messages: int = 0


class ByChannelSummary(BaseModel):
    customer: ChannelGroupSummary = Field(default_factory=ChannelGroupSummary)
    seller: ChannelGroupSummary = Field(default_factory=ChannelGroupSummary)
    dropshipper: ChannelGroupSummary = Field(default_factory=ChannelGroupSummary)


class AdminCommunicationSummaryResponse(BaseModel):
    open_count: int = 0
    pending_count: int = 0
    resolved_count: int = 0
    closed_count: int = 0
    unassigned_count: int = 0
    unread_conversations_count: int = 0
    total_unread_messages: int = 0
    by_type: list[ChannelSummaryCount] = Field(default_factory=list)
    by_channel: ByChannelSummary = Field(default_factory=ByChannelSummary)
