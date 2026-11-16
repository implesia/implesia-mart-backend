"""Admin inventory: suppliers, purchases, the stock ledger, and Excel."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, RequireEditor, no_store
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.models.inventory import ImportKind
from app.rate_limit import limiter
from app.schemas.inventory import (
    AdjustmentCreate,
    DateRangeQuery,
    ExportKind,
    ImportPreview,
    ImportResult,
    MovementList,
    MovementQuery,
    MovementRead,
    OpeningStockResult,
    PurchaseCreate,
    PurchaseList,
    PurchaseQuery,
    PurchaseRead,
    SupplierCreate,
    SupplierList,
    SupplierQuery,
    SupplierRead,
    SupplierUpdate,
)
from app.services import inventory_service
from app.services.inventory_excel import MAX_IMPORT_BYTES

router = APIRouter(dependencies=[Depends(no_store)])
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/suppliers", response_model=SupplierList)
async def list_suppliers(
    db: DbSession, user: CurrentUser, query: Annotated[SupplierQuery, Depends()]
) -> SupplierList:
    del user
    return await inventory_service.list_suppliers(db, query)


@router.post("/suppliers", response_model=SupplierRead, status_code=201)
@limiter.limit(settings.rate_limit_product_writes)
async def create_supplier(
    request: Request, db: DbSession, actor: RequireEditor, payload: SupplierCreate
) -> SupplierRead:
    del request
    return await inventory_service.create_supplier(db, payload, actor)


@router.get("/suppliers/{supplier_id}", response_model=SupplierRead)
async def get_supplier(db: DbSession, user: CurrentUser, supplier_id: uuid.UUID) -> SupplierRead:
    del user
    return await inventory_service.get_supplier(db, supplier_id)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_supplier(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    supplier_id: uuid.UUID,
    payload: SupplierUpdate,
) -> SupplierRead:
    del request
    return await inventory_service.update_supplier(db, supplier_id, payload, actor)


@router.get("/purchases", response_model=PurchaseList)
async def list_purchases(
    db: DbSession, user: CurrentUser, query: Annotated[PurchaseQuery, Depends()]
) -> PurchaseList:
    del user
    return await inventory_service.list_purchases(db, query)


@router.post("/purchases", response_model=PurchaseRead, status_code=201)
@limiter.limit(settings.rate_limit_product_writes)
async def create_purchase(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    payload: PurchaseCreate,
    background: BackgroundTasks,
) -> PurchaseRead:
    del request
    return await inventory_service.create_purchase(db, payload, actor, background)


@router.get("/purchases/{purchase_id}", response_model=PurchaseRead)
async def get_purchase(db: DbSession, user: CurrentUser, purchase_id: uuid.UUID) -> PurchaseRead:
    del user
    return await inventory_service.get_purchase(db, purchase_id)


@router.get("/movements", response_model=MovementList)
async def list_movements(
    db: DbSession, user: CurrentUser, query: Annotated[MovementQuery, Depends()]
) -> MovementList:
    del user
    return await inventory_service.list_movements(db, query)


@router.post("/adjustments", response_model=MovementRead, status_code=201)
@limiter.limit(settings.rate_limit_product_writes)
async def adjust_stock(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    payload: AdjustmentCreate,
    background: BackgroundTasks,
) -> MovementRead:
    del request
    return await inventory_service.adjust_stock(db, payload, actor, background)


@router.post("/opening-stock", response_model=OpeningStockResult)
@limiter.limit(settings.rate_limit_product_writes)
async def opening_stock(
    request: Request, db: DbSession, actor: RequireEditor
) -> OpeningStockResult:
    del request
    return await inventory_service.record_opening_stock(db, actor_id=actor.id)


@router.get("/exports/{kind}")
async def export_inventory(
    db: DbSession,
    user: CurrentUser,
    kind: ExportKind,
    query: Annotated[DateRangeQuery, Depends()],
) -> StreamingResponse:
    del user
    name, payload = await inventory_service.export_bytes(db, kind, query)
    return _xlsx(name, payload)


@router.get("/imports/templates/{kind}")
async def import_template(user: CurrentUser, kind: ImportKind) -> StreamingResponse:
    del user
    name, payload = inventory_service.import_template(kind.value)
    return _xlsx(name, payload)


@router.post("/imports/preview", response_model=ImportPreview)
@limiter.limit(settings.rate_limit_product_writes)
async def preview_import(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    import_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> ImportPreview:
    del request, user
    data, filename = await _upload(file)
    return await inventory_service.preview_import(db, _import_kind(import_type), data, filename)


@router.post("/imports/confirm", response_model=ImportResult)
@limiter.limit(settings.rate_limit_product_writes)
async def confirm_import(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    background: BackgroundTasks,
    import_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    confirm_duplicate: Annotated[bool, Form()] = False,
) -> ImportResult:
    del request
    data, filename = await _upload(file)
    return await inventory_service.confirm_import(
        db,
        _import_kind(import_type),
        data,
        filename,
        actor=actor,
        confirm_duplicate=confirm_duplicate,
        background=background,
    )


def _import_kind(value: str) -> str:
    try:
        return ImportKind(value).value
    except ValueError as exc:
        raise UnprocessableError("Unknown import type") from exc


async def _upload(file: UploadFile) -> tuple[bytes, str]:
    data = await file.read(MAX_IMPORT_BYTES + 1)
    return data, file.filename or ""


def _xlsx(name: str, payload: bytes) -> StreamingResponse:
    return StreamingResponse(
        iter([payload]),
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
