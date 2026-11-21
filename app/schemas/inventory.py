import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator

from app.models.inventory import ImportKind, MovementType
from app.schemas.common import Page, WriteModel
from app.schemas.product import MAX_QUANTITY, CostPrice

ExportKind = Literal["products", "purchases", "movements"]


def _clean(value: str) -> str:
    return value.strip()


class SupplierCreate(WriteModel):
    name: str = Field(min_length=1, max_length=160)
    phone: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=500)

    @field_validator("name", "phone", "address", "note")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _clean(value)


class SupplierUpdate(WriteModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("name", "phone", "address", "note")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean(value)


class SupplierRead(WriteModel):
    model_config = {"extra": "ignore"}

    id: uuid.UUID
    name: str
    phone: str
    address: str
    note: str
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class SupplierQuery(WriteModel):
    model_config = {"extra": "ignore"}

    q: str | None = Field(default=None, max_length=80)
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PurchaseItemCreate(WriteModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=1, le=MAX_QUANTITY)
    unit_cost: CostPrice


class PurchaseCreate(WriteModel):
    supplier_id: uuid.UUID
    purchased_on: date
    invoice_no: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=500)
    items: list[PurchaseItemCreate] = Field(min_length=1, max_length=100)

    @field_validator("invoice_no", "note")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _clean(value)


class PurchaseItemRead(WriteModel):
    model_config = {"extra": "ignore"}

    id: uuid.UUID
    product_id: uuid.UUID | None
    variant_id: uuid.UUID | None
    quantity: int
    unit_cost: CostPrice


class PurchaseRead(WriteModel):
    model_config = {"extra": "ignore"}

    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str
    purchased_on: date
    invoice_no: str
    note: str
    items: list[PurchaseItemRead]
    created_at: datetime


class PurchaseQuery(WriteModel):
    model_config = {"extra": "ignore"}

    supplier_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from is after date_to")
        return self

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class MovementRead(WriteModel):
    model_config = {"extra": "ignore"}

    id: uuid.UUID
    product_id: uuid.UUID | None
    variant_id: uuid.UUID | None
    product_title: str
    sku: str
    quantity: int
    movement_type: MovementType
    unit_cost: CostPrice | None
    order_id: uuid.UUID | None
    purchase_id: uuid.UUID | None
    import_batch_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    note: str
    created_at: datetime


class MovementQuery(WriteModel):
    model_config = {"extra": "ignore"}

    product_id: uuid.UUID | None = None
    movement_type: MovementType | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from is after date_to")
        return self

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class AdjustmentCreate(WriteModel):
    """Pieces to add (positive) or remove (negative). The reason is required."""

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=-MAX_QUANTITY, le=MAX_QUANTITY)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("A reason is required")
        return text

    @field_validator("quantity")
    @classmethod
    def _nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Enter how many pieces to add or remove")
        return value


class OpeningStockResult(WriteModel):
    model_config = {"extra": "ignore"}

    created: int
    already_recorded: int
    untracked: int


class DateRangeQuery(WriteModel):
    model_config = {"extra": "ignore"}

    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from is after date_to")
        return self


class ImportPreviewRow(WriteModel):
    model_config = {"extra": "ignore"}

    row: int
    valid: bool
    action: str
    errors: list[str]
    summary: str


class ImportPreview(WriteModel):
    model_config = {"extra": "ignore"}

    import_type: ImportKind
    file_hash: str
    duplicate: bool
    valid_count: int
    invalid_count: int
    rows: list[ImportPreviewRow]


class ImportResult(WriteModel):
    model_config = {"extra": "ignore"}

    import_type: ImportKind
    file_hash: str
    batch_id: uuid.UUID | None
    saved: int
    skipped: int
    rows: list[ImportPreviewRow]


def _money_float(value: Decimal) -> float:
    return float(value)


InventoryMoney = Annotated[
    Decimal,
    PlainSerializer(_money_float, return_type=float, when_used="json"),
]


class SupplierMergeTarget(BaseModel):
    id: uuid.UUID
    name: str
    phone: str


class SupplierDeleteImpact(BaseModel):
    supplier_name: str
    purchases_count: int
    total_purchase_amount: InventoryMoney
    linked_products_count: int
    available_merge_targets: list[SupplierMergeTarget]


class SupplierDeleteRequest(WriteModel):
    mode: Literal["merge", "archive", "hard_delete"] = "archive"
    target_supplier_id: uuid.UUID | None = None
    reason: str = Field(default="", max_length=500)
    unlink_products: bool = True

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        return value.strip()


class SupplierDeleteResult(BaseModel):
    deleted_supplier_id: uuid.UUID
    deleted_supplier_name: str
    mode: Literal["merge", "archive", "hard_delete"]
    target_supplier_id: uuid.UUID | None = None
    moved_purchases_count: int = 0
    moved_products_count: int = 0
    unlinked_products_count: int = 0


SupplierList = Page[SupplierRead]
PurchaseList = Page[PurchaseRead]
MovementList = Page[MovementRead]
