"""Suppliers, purchases, stock adjustments, opening stock, and Excel import/export.

On-hand counts stay on the product or variant row. This module only adds a
`stock_movements` row in the same transaction as the count change. Sales are
staged during order claim and inserted after the order row exists, still
before that transaction commits.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from starlette.background import BackgroundTasks

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.audit_event import AuditAction
from app.models.inventory import (
    ImportBatch,
    ImportKind,
    MovementType,
    Purchase,
    PurchaseItem,
    StockMovement,
    Supplier,
)
from app.models.product import Product, ProductVariant, StockStatus
from app.models.user import User
from app.schemas.common import page_count
from app.schemas.inventory import (
    AdjustmentCreate,
    DateRangeQuery,
    ImportPreview,
    ImportPreviewRow,
    ImportResult,
    MovementList,
    MovementQuery,
    MovementRead,
    OpeningStockResult,
    PurchaseCreate,
    PurchaseItemRead,
    PurchaseList,
    PurchaseQuery,
    PurchaseRead,
    SupplierCreate,
    SupplierList,
    SupplierQuery,
    SupplierRead,
    SupplierUpdate,
)
from app.schemas.product import MAX_QUANTITY
from app.services import audit_service, telegram_notify, variant_service
from app.services.inventory_excel import (
    COST_COLUMNS,
    MAX_EXPORT_ROWS,
    MOVEMENT_EXPORT_COLUMNS,
    OPENING_COLUMNS,
    PRODUCT_EXPORT_COLUMNS,
    PURCHASE_COLUMNS,
    PURCHASE_EXPORT_COLUMNS,
    STOCK_COUNT_COLUMNS,
    cell_date,
    cell_int,
    cell_money,
    cell_str,
    file_hash,
    load_table,
    template_bytes,
    workbook_bytes,
)

CENT = Decimal("0.01")
MONEY_MAX = Decimal("9999999999.99")
_Expr = ColumnElement[Any]
PENDING_SALES = "inventory_pending_sales"
_COLUMNS = {
    ImportKind.PURCHASES.value: PURCHASE_COLUMNS,
    ImportKind.OPENING.value: OPENING_COLUMNS,
    ImportKind.STOCK_COUNT.value: STOCK_COUNT_COLUMNS,
    ImportKind.COST_PRICE.value: COST_COLUMNS,
}


@dataclass(frozen=True)
class PendingSale:
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    quantity: int
    unit_cost: Decimal | None


@dataclass
class ClassifiedRow:
    number: int
    errors: list[str] = field(default_factory=list)
    action: str = "none"
    summary: str = ""
    product_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    quantity: int | None = None
    counted: int | None = None
    unit_cost: Decimal | None = None
    supplier_name: str = ""
    supplier_phone: str = ""
    supplier_address: str = ""
    supplier_note: str = ""
    invoice_no: str = ""
    purchased_on: date | None = None
    reason: str = ""
    product_title: str = ""
    sku: str = ""
    quantity_blank: bool = False

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass
class _Bucket:
    product_id: uuid.UUID
    has_variants: bool
    cost: Decimal | None
    quantity: int | None
    status: str
    variants: dict[uuid.UUID, int | None]
    original_cost: Decimal | None
    original_quantity: int | None
    original_status: str
    original_variants: dict[uuid.UUID, int | None]


def weighted_average_cost(
    old_stock: int | None,
    old_cost: Decimal | None,
    incoming_qty: int,
    incoming_cost: Decimal,
) -> Decimal:
    """Cost after receiving `incoming_qty` units at `incoming_cost`.

    The new unit cost is used when `old_cost` is missing, or when `old_stock`
    is missing or not positive (nothing on hand to weigh). Otherwise
    `(old_stock × old_cost + incoming_qty × incoming_cost) / (old_stock + incoming_qty)`,
    rounded half up to 2 decimal places. Both costs are rounded to 2 decimals
    before the division.
    """
    if incoming_qty <= 0:
        raise ValueError("incoming quantity must be positive")
    incoming = _money(incoming_cost)
    if incoming < 0:
        raise ValueError("unit cost cannot be negative")
    if old_cost is None or old_stock is None or old_stock <= 0:
        return incoming
    total_qty = old_stock + incoming_qty
    total_cost = (Decimal(old_stock) * _money(old_cost)) + (Decimal(incoming_qty) * incoming)
    return (total_cost / Decimal(total_qty)).quantize(CENT, rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(_money(value), "f")


def stage_sale(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    variant_id: uuid.UUID | None,
    quantity: int,
    unit_cost: Decimal | None,
) -> None:
    """Remember a sale until `attach_pending_sales` inserts it."""
    if quantity == 0:
        return
    pending: list[PendingSale] = db.info.setdefault(PENDING_SALES, [])
    pending.append(
        PendingSale(
            product_id=product_id,
            variant_id=variant_id,
            quantity=quantity,
            unit_cost=unit_cost,
        )
    )


def attach_pending_sales(db: AsyncSession, order_id: uuid.UUID) -> None:
    """Insert staged sales. Call this after the order row has been flushed."""
    pending: list[PendingSale] = db.info.pop(PENDING_SALES, [])
    for sale in pending:
        add_movement(
            db,
            product_id=sale.product_id,
            variant_id=sale.variant_id,
            quantity=sale.quantity,
            movement_type=MovementType.SALE.value,
            unit_cost=sale.unit_cost,
            order_id=order_id,
        )


def clear_pending_sales(db: AsyncSession) -> None:
    db.info.pop(PENDING_SALES, None)


def add_movement(
    db: AsyncSession,
    *,
    product_id: uuid.UUID | None,
    variant_id: uuid.UUID | None,
    quantity: int,
    movement_type: str,
    unit_cost: Decimal | None,
    order_id: uuid.UUID | None = None,
    purchase_id: uuid.UUID | None = None,
    import_batch_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    note: str = "",
) -> StockMovement:
    row = StockMovement(
        id=uuid.uuid4(),
        product_id=product_id,
        variant_id=variant_id,
        quantity=quantity,
        movement_type=movement_type,
        unit_cost=unit_cost,
        order_id=order_id,
        purchase_id=purchase_id,
        import_batch_id=import_batch_id,
        actor_id=actor_id,
        note=note[:500],
    )
    db.add(row)
    return row


async def list_suppliers(db: AsyncSession, query: SupplierQuery) -> SupplierList:
    filters: list[_Expr] = []
    if query.q and query.q.strip():
        filters.append(func.lower(Supplier.name).like(_contains(query.q), escape="\\"))
    total = await _count(db, Supplier, filters)
    rows = (
        await db.scalars(
            select(Supplier)
            .where(*filters)
            .order_by(Supplier.name, Supplier.id)
            .offset(query.offset)
            .limit(query.page_size)
        )
    ).all()
    return SupplierList(
        items=[_supplier_read(row) for row in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=page_count(total, query.page_size),
    )


async def get_supplier(db: AsyncSession, supplier_id: uuid.UUID) -> SupplierRead:
    return _supplier_read(await _supplier(db, supplier_id))


async def create_supplier(
    db: AsyncSession, payload: SupplierCreate, actor: User
) -> SupplierRead:
    del actor
    row = Supplier(
        id=uuid.uuid4(),
        name=payload.name,
        phone=payload.phone,
        address=payload.address,
        note=payload.note,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _supplier_read(row)


async def update_supplier(
    db: AsyncSession, supplier_id: uuid.UUID, payload: SupplierUpdate, actor: User
) -> SupplierRead:
    del actor
    row = await _supplier(db, supplier_id)
    if payload.name is not None:
        row.name = payload.name
    if payload.phone is not None:
        row.phone = payload.phone
    if payload.address is not None:
        row.address = payload.address
    if payload.note is not None:
        row.note = payload.note
    await db.commit()
    await db.refresh(row)
    return _supplier_read(row)


async def list_purchases(db: AsyncSession, query: PurchaseQuery) -> PurchaseList:
    filters = _purchase_filters(query)
    total = await _count(db, Purchase, filters)
    rows = (
        await db.scalars(
            select(Purchase)
            .where(*filters)
            .options(selectinload(Purchase.items))
            .order_by(Purchase.purchased_on.desc(), Purchase.created_at.desc())
            .offset(query.offset)
            .limit(query.page_size)
        )
    ).all()
    names = await _supplier_names(db, [row.supplier_id for row in rows])
    return PurchaseList(
        items=[_purchase_read(row, names.get(row.supplier_id, "")) for row in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=page_count(total, query.page_size),
    )


async def get_purchase(db: AsyncSession, purchase_id: uuid.UUID) -> PurchaseRead:
    row = await _purchase(db, purchase_id)
    names = await _supplier_names(db, [row.supplier_id])
    return _purchase_read(row, names.get(row.supplier_id, ""))


async def create_purchase(
    db: AsyncSession,
    payload: PurchaseCreate,
    actor: User,
    background: BackgroundTasks | None = None,
) -> PurchaseRead:
    telegram_notify.discard_low_stock(db)
    supplier = await db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise NotFoundError("Supplier not found")
    lines: list[tuple[uuid.UUID, uuid.UUID | None, int, Decimal]] = []
    for item in payload.items:
        product, variant, errors = await _resolve_target(
            db, item.product_id, "", item.variant_id
        )
        if errors or product is None:
            raise UnprocessableError(errors[0] if errors else "Product not found")
        _require_bucket(product, variant)
        lines.append(
            (
                product.id,
                variant.id if variant is not None else None,
                item.quantity,
                _money(item.unit_cost),
            )
        )
    product_ids = sorted({product_id for product_id, *_rest in lines})
    await _lock_products(db, product_ids)
    buckets = {product_id: await _load_bucket(db, product_id) for product_id in product_ids}
    purchase_id = uuid.uuid4()
    for product_id, variant_id, quantity, unit_cost in lines:
        _apply_receipt(buckets[product_id], variant_id, quantity, unit_cost)
        add_movement(
            db,
            product_id=product_id,
            variant_id=variant_id,
            quantity=quantity,
            movement_type=MovementType.PURCHASE.value,
            unit_cost=unit_cost,
            purchase_id=purchase_id,
            actor_id=actor.id,
            note="",
        )
    purchase = Purchase(
        id=purchase_id,
        supplier_id=supplier.id,
        purchased_on=payload.purchased_on,
        invoice_no=payload.invoice_no,
        note=payload.note,
    )
    db.add(purchase)
    for product_id, variant_id, quantity, unit_cost in lines:
        db.add(
            PurchaseItem(
                id=uuid.uuid4(),
                purchase_id=purchase_id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                unit_cost=unit_cost,
            )
        )
    for bucket in buckets.values():
        await _persist_bucket(db, bucket, actor.id)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        telegram_notify.discard_low_stock(db)
        raise ConflictError("Could not save this purchase") from exc
    telegram_notify.flush_low_stock(db, background)
    return await get_purchase(db, purchase_id)


async def list_movements(db: AsyncSession, query: MovementQuery) -> MovementList:
    filters = _movement_filters(query)
    total = await _count(db, StockMovement, filters)
    rows = (
        await db.scalars(
            select(StockMovement)
            .where(*filters)
            .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .offset(query.offset)
            .limit(query.page_size)
        )
    ).all()
    return MovementList(
        items=await _movement_reads(db, rows),
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=page_count(total, query.page_size),
    )


async def adjust_stock(
    db: AsyncSession,
    payload: AdjustmentCreate,
    actor: User,
    background: BackgroundTasks | None = None,
) -> MovementRead:
    telegram_notify.discard_low_stock(db)
    product, variant, errors = await _resolve_target(
        db, payload.product_id, "", payload.variant_id
    )
    if errors or product is None:
        raise UnprocessableError(errors[0] if errors else "Product not found")
    _require_bucket(product, variant)
    await _lock_products(db, [product.id])
    bucket = await _load_bucket(db, product.id)
    variant_id = variant.id if variant is not None else None
    current = _bucket_qty(bucket, variant_id)
    if current is None:
        raise UnprocessableError("This product has no stock count")
    new_qty = current + payload.quantity
    if new_qty < 0:
        raise UnprocessableError("Not enough stock to remove that many")
    _set_bucket_qty(bucket, variant_id, new_qty)
    movement = add_movement(
        db,
        product_id=product.id,
        variant_id=variant_id,
        quantity=payload.quantity,
        movement_type=MovementType.ADJUSTMENT.value,
        unit_cost=bucket.cost,
        actor_id=actor.id,
        note=payload.reason,
    )
    await _persist_bucket(db, bucket, actor.id)
    await db.commit()
    telegram_notify.flush_low_stock(db, background)
    await db.refresh(movement)
    reads = await _movement_reads(db, [movement])
    return reads[0]


async def record_opening_stock(
    db: AsyncSession, *, actor_id: uuid.UUID | None
) -> OpeningStockResult:
    """One opening movement per tracked product or variant. Stock is not changed."""
    products = (await db.scalars(select(Product).order_by(Product.id))).all()
    created = 0
    already = 0
    untracked = 0
    for product_id in [row.id for row in products]:
        await _lock_products(db, [product_id])
        product = await db.get(Product, product_id, populate_existing=True)
        if product is None:
            continue
        if product.has_variants:
            variants = (
                await db.scalars(
                    select(ProductVariant)
                    .where(ProductVariant.product_id == product.id)
                    .order_by(ProductVariant.id)
                )
            ).all()
            tracked = [row for row in variants if row.quantity is not None]
            if not tracked:
                untracked += 1
                continue
            for variant in tracked:
                if await _opening_exists(db, product.id, variant.id):
                    already += 1
                    continue
                add_movement(
                    db,
                    product_id=product.id,
                    variant_id=variant.id,
                    quantity=variant.quantity or 0,
                    movement_type=MovementType.OPENING.value,
                    unit_cost=product.cost_price,
                    actor_id=actor_id,
                    note="Opening stock from the current count",
                )
                created += 1
            continue
        if product.quantity is None:
            untracked += 1
            continue
        if await _opening_exists(db, product.id, None):
            already += 1
            continue
        add_movement(
            db,
            product_id=product.id,
            variant_id=None,
            quantity=product.quantity,
            movement_type=MovementType.OPENING.value,
            unit_cost=product.cost_price,
            actor_id=actor_id,
            note="Opening stock from the current count",
        )
        created += 1
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Opening stock was already being recorded. Run it again.") from exc
    return OpeningStockResult(created=created, already_recorded=already, untracked=untracked)


async def export_bytes(db: AsyncSession, kind: str, query: DateRangeQuery) -> tuple[str, bytes]:
    if kind == "products":
        return "products.xlsx", await _export_products(db, query)
    if kind == "purchases":
        return "purchases.xlsx", await _export_purchases(db, query)
    if kind == "movements":
        return "stock-movements.xlsx", await _export_movements(db, query)
    raise UnprocessableError("Unknown export")


def import_template(kind: str) -> tuple[str, bytes]:
    if kind not in _COLUMNS:
        raise UnprocessableError("Unknown import template")
    return f"{kind.replace('_', '-')}-template.xlsx", template_bytes(kind)


async def preview_import(
    db: AsyncSession, kind: str, data: bytes, filename: str
) -> ImportPreview:
    rows = await _classify(db, kind, data, filename)
    digest = file_hash(data)
    duplicate = await _hash_seen(db, digest)
    valid = sum(1 for row in rows if row.valid)
    return ImportPreview(
        import_type=ImportKind(kind),
        file_hash=digest,
        duplicate=duplicate,
        valid_count=valid,
        invalid_count=len(rows) - valid,
        rows=[_preview_row(row) for row in rows],
    )


async def confirm_import(
    db: AsyncSession,
    kind: str,
    data: bytes,
    filename: str,
    *,
    actor: User,
    confirm_duplicate: bool,
    background: BackgroundTasks | None = None,
) -> ImportResult:
    telegram_notify.discard_low_stock(db)
    rows = await _classify(db, kind, data, filename)
    digest = file_hash(data)
    if rows and all(not row.valid for row in rows):
        raise UnprocessableError(
            "Nothing was imported. Every row has an error.",
            details={"rows": [_preview_row(row).model_dump(mode="json") for row in rows]},
        )
    if await _hash_seen(db, digest) and not confirm_duplicate:
        raise ConflictError(
            "This file was already imported. Confirm to import it again.",
            details={"file_hash": digest},
        )
    actionable = [row for row in rows if row.valid and row.action != "none"]
    if not actionable:
        return ImportResult(
            import_type=ImportKind(kind),
            file_hash=digest,
            batch_id=None,
            saved=0,
            skipped=sum(1 for row in rows if not row.valid),
            rows=[_preview_row(row) for row in rows],
        )
    batch = ImportBatch(
        id=uuid.uuid4(),
        file_hash=digest,
        import_type=kind,
        file_name=_safe_name(filename),
        row_count=len(actionable),
        actor_id=actor.id,
    )
    db.add(batch)
    if kind == ImportKind.PURCHASES.value:
        await _import_purchases(db, actionable, batch, actor.id)
    elif kind == ImportKind.OPENING.value:
        await _import_opening(db, actionable, batch, actor.id)
    elif kind == ImportKind.STOCK_COUNT.value:
        await _import_counts(db, actionable, batch, actor.id)
    elif kind == ImportKind.COST_PRICE.value:
        await _import_costs(db, actionable, batch, actor.id)
    else:
        raise UnprocessableError("Unknown import type")
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        telegram_notify.discard_low_stock(db)
        raise ConflictError("Could not import this workbook. Nothing was saved.") from exc
    telegram_notify.flush_low_stock(db, background)
    return ImportResult(
        import_type=ImportKind(kind),
        file_hash=digest,
        batch_id=batch.id,
        saved=len(actionable),
        skipped=sum(1 for row in rows if not row.valid),
        rows=[_preview_row(row) for row in rows],
    )


async def _import_purchases(
    db: AsyncSession, rows: list[ClassifiedRow], batch: ImportBatch, actor_id: uuid.UUID
) -> None:
    product_ids = sorted({row.product_id for row in rows if row.product_id is not None})
    await _lock_products(db, product_ids)
    buckets = {product_id: await _load_bucket(db, product_id) for product_id in product_ids}
    groups: dict[tuple[str, str, date], list[ClassifiedRow]] = defaultdict(list)
    for row in rows:
        if row.purchased_on is None:
            continue
        groups[(row.supplier_name, row.invoice_no, row.purchased_on)].append(row)
    suppliers = await _suppliers_for_import(db, rows)
    for (name, invoice, purchased_on), lines in groups.items():
        purchase_id = uuid.uuid4()
        db.add(
            Purchase(
                id=purchase_id,
                supplier_id=suppliers[name],
                purchased_on=purchased_on,
                invoice_no=invoice,
                import_batch_id=batch.id,
            )
        )
        for line in lines:
            if line.product_id is None or line.quantity is None or line.unit_cost is None:
                continue
            bucket = buckets[line.product_id]
            _apply_receipt(bucket, line.variant_id, line.quantity, line.unit_cost)
            db.add(
                PurchaseItem(
                    id=uuid.uuid4(),
                    purchase_id=purchase_id,
                    product_id=line.product_id,
                    variant_id=line.variant_id,
                    quantity=line.quantity,
                    unit_cost=line.unit_cost,
                )
            )
            add_movement(
                db,
                product_id=line.product_id,
                variant_id=line.variant_id,
                quantity=line.quantity,
                movement_type=MovementType.PURCHASE.value,
                unit_cost=line.unit_cost,
                purchase_id=purchase_id,
                actor_id=actor_id,
            )
    for bucket in buckets.values():
        await _persist_bucket(db, bucket, actor_id)


async def _import_opening(
    db: AsyncSession, rows: list[ClassifiedRow], batch: ImportBatch, actor_id: uuid.UUID
) -> None:
    product_ids = sorted({row.product_id for row in rows if row.product_id is not None})
    await _lock_products(db, product_ids)
    for row in rows:
        if row.product_id is None or row.quantity is None:
            continue
        current = await _locked_quantity(db, row.product_id, row.variant_id)
        if current != row.quantity or await _opening_exists(db, row.product_id, row.variant_id):
            raise ConflictError("Stock changed while importing. Nothing was saved. Preview again.")
        add_movement(
            db,
            product_id=row.product_id,
            variant_id=row.variant_id,
            quantity=current,
            movement_type=MovementType.OPENING.value,
            unit_cost=await _product_cost(db, row.product_id),
            import_batch_id=batch.id,
            actor_id=actor_id,
            note="Opening stock import",
        )


async def _import_counts(
    db: AsyncSession, rows: list[ClassifiedRow], batch: ImportBatch, actor_id: uuid.UUID
) -> None:
    product_ids = sorted({row.product_id for row in rows if row.product_id is not None})
    await _lock_products(db, product_ids)
    buckets = {product_id: await _load_bucket(db, product_id) for product_id in product_ids}
    for row in rows:
        if row.product_id is None or row.quantity is None:
            continue
        bucket = buckets[row.product_id]
        current = _bucket_qty(bucket, row.variant_id)
        if current is None or row.counted is None:
            continue
        _set_bucket_qty(bucket, row.variant_id, row.counted)
        add_movement(
            db,
            product_id=row.product_id,
            variant_id=row.variant_id,
            quantity=row.counted - current,
            movement_type=MovementType.ADJUSTMENT.value,
            unit_cost=bucket.cost,
            import_batch_id=batch.id,
            actor_id=actor_id,
            note=row.reason or "Stock count",
        )
    for bucket in buckets.values():
        await _persist_bucket(db, bucket, actor_id)


async def _import_costs(
    db: AsyncSession, rows: list[ClassifiedRow], batch: ImportBatch, actor_id: uuid.UUID
) -> None:
    product_ids = sorted({row.product_id for row in rows if row.product_id is not None})
    await _lock_products(db, product_ids)
    buckets = {product_id: await _load_bucket(db, product_id) for product_id in product_ids}
    for row in rows:
        if row.product_id is None or row.unit_cost is None:
            continue
        buckets[row.product_id].cost = row.unit_cost
        add_movement(
            db,
            product_id=row.product_id,
            variant_id=row.variant_id,
            quantity=0,
            movement_type=MovementType.ADJUSTMENT.value,
            unit_cost=row.unit_cost,
            import_batch_id=batch.id,
            actor_id=actor_id,
            note="Cost price import",
        )
    for bucket in buckets.values():
        await _persist_bucket(db, bucket, actor_id)


async def _classify(
    db: AsyncSession, kind: str, data: bytes, filename: str
) -> list[ClassifiedRow]:
    columns = _COLUMNS.get(kind)
    if columns is None:
        raise UnprocessableError("Unknown import type")
    table = load_table(data, filename, columns)
    rows = [_structural(kind, number, cells) for number, cells in table]
    await _resolve_rows(db, rows)
    await _decide_rows(db, kind, rows)
    return rows


def _structural(kind: str, number: int, cells: dict[str, object]) -> ClassifiedRow:
    row = ClassifiedRow(number=number)
    product_text = cell_str(cells.get("product_id"))
    variant_text = cell_str(cells.get("variant_id"))
    row.sku = cell_str(cells.get("sku"))
    if product_text:
        try:
            row.product_id = uuid.UUID(product_text)
        except ValueError:
            row.errors.append("product_id is not a valid id.")
    if variant_text:
        try:
            row.variant_id = uuid.UUID(variant_text)
        except ValueError:
            row.errors.append("variant_id is not a valid id.")
    if not product_text and not variant_text and not row.sku:
        row.errors.append("Enter a product_id or a sku. Products are never matched by name.")
    if kind == ImportKind.PURCHASES.value:
        _purchase_fields(row, cells)
    elif kind == ImportKind.OPENING.value:
        _optional_qty(row, cells.get("quantity"), label="quantity")
    elif kind == ImportKind.STOCK_COUNT.value:
        counted = _required_qty(row, cells.get("counted_qty"), label="counted_qty", minimum=0)
        row.quantity = counted
        row.reason = cell_str(cells.get("reason"))
        if not row.reason:
            row.errors.append("Reason is required.")
        elif len(row.reason) > 500:
            row.errors.append("Reason must be 500 characters or fewer.")
    elif kind == ImportKind.COST_PRICE.value:
        row.unit_cost = _required_money(row, cells.get("unit_cost"))
    return row


def _purchase_fields(row: ClassifiedRow, cells: dict[str, object]) -> None:
    row.supplier_name = cell_str(cells.get("supplier_name"))
    row.supplier_phone = cell_str(cells.get("supplier_phone"))
    row.supplier_address = cell_str(cells.get("supplier_address"))
    row.supplier_note = cell_str(cells.get("supplier_note"))
    row.invoice_no = cell_str(cells.get("invoice_no"))
    if not row.supplier_name:
        row.errors.append("Enter the supplier name.")
    elif len(row.supplier_name) > 160:
        row.errors.append("Supplier name must be 160 characters or fewer.")
    if len(row.supplier_phone) > 40:
        row.errors.append("Supplier phone must be 40 characters or fewer.")
    if len(row.supplier_address) > 500:
        row.errors.append("Supplier address must be 500 characters or fewer.")
    if len(row.supplier_note) > 500:
        row.errors.append("Supplier note must be 500 characters or fewer.")
    if len(row.invoice_no) > 64:
        row.errors.append("Invoice number must be 64 characters or fewer.")
    raw_date = cells.get("purchased_on")
    if cell_str(raw_date) == "":
        row.errors.append("Enter the purchase date as YYYY-MM-DD.")
    else:
        row.purchased_on = cell_date(raw_date)
        if row.purchased_on is None:
            row.errors.append("Enter the purchase date as YYYY-MM-DD.")
    row.quantity = _required_qty(row, cells.get("quantity"), label="quantity", minimum=1)
    row.unit_cost = _required_money(row, cells.get("unit_cost"))


def _optional_qty(row: ClassifiedRow, value: object, *, label: str) -> None:
    if cell_str(value) == "":
        row.quantity_blank = True
        return
    row.quantity = _required_qty(row, value, label=label, minimum=0)


def _required_qty(row: ClassifiedRow, value: object, *, label: str, minimum: int) -> int | None:
    if cell_str(value) == "":
        row.errors.append(f"Enter {label}.")
        return None
    parsed = cell_int(value)
    if parsed is None or parsed < minimum or parsed > MAX_QUANTITY:
        row.errors.append(f"{label} must be a whole number from {minimum} to {MAX_QUANTITY}.")
        return None
    return parsed


def _required_money(row: ClassifiedRow, value: object) -> Decimal | None:
    if cell_str(value) == "":
        row.errors.append("Enter a unit cost.")
        return None
    parsed = cell_money(value)
    if parsed is None or parsed < 0 or parsed > MONEY_MAX:
        row.errors.append("Unit cost must be zero or greater.")
        return None
    return _money(parsed)


async def _resolve_rows(db: AsyncSession, rows: list[ClassifiedRow]) -> None:
    for row in rows:
        if row.product_id is None and row.variant_id is None and not row.sku:
            continue
        product, variant, errors = await _resolve_target(
            db, row.product_id, row.sku, row.variant_id
        )
        row.errors.extend(errors)
        if product is None:
            continue
        row.product_id = product.id
        row.product_title = product.title
        row.variant_id = variant.id if variant is not None else None
        row.sku = variant.sku if variant is not None and variant.sku else row.sku


async def _decide_rows(db: AsyncSession, kind: str, rows: list[ClassifiedRow]) -> None:
    seen: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
    supplier_counts = await _supplier_counts(
        db, [row.supplier_name for row in rows if row.supplier_name]
    )
    for row in rows:
        if row.product_id is None or _identity_error(row):
            continue
        product = await db.get(Product, row.product_id)
        variant = await db.get(ProductVariant, row.variant_id) if row.variant_id else None
        if product is None:
            row.errors.append("No product matches this product_id.")
            continue
        variant_key = None if kind == ImportKind.COST_PRICE.value else (
            variant.id if variant is not None else None
        )
        key = (product.id, variant_key)
        if kind != ImportKind.PURCHASES.value and key in seen:
            row.errors.append("This product or option appears more than once in the file.")
            continue
        if kind != ImportKind.PURCHASES.value:
            seen.add(key)
        if kind == ImportKind.PURCHASES.value:
            if supplier_counts.get(row.supplier_name, 0) > 1:
                row.errors.append(f"More than one supplier is named '{row.supplier_name}'.")
            if row.quantity and row.unit_cost is not None and not row.errors:
                row.action = "purchase"
                row.summary = f"Receive {row.quantity} at {row.unit_cost} ({product.title})"
            continue
        current = variant.quantity if variant is not None else product.quantity
        if kind == ImportKind.OPENING.value:
            _decide_opening(row, current, await _opening_exists(db, product.id, row.variant_id))
        elif kind == ImportKind.STOCK_COUNT.value:
            _decide_count(row, current)
        elif kind == ImportKind.COST_PRICE.value and row.unit_cost is not None and not row.errors:
            row.action = "cost"
            previous = _money_text(product.cost_price) or "none"
            row.summary = f"Cost price {previous} → {row.unit_cost} ({product.title})"


def _decide_opening(row: ClassifiedRow, current: int | None, exists: bool) -> None:
    if current is None:
        row.errors.append("This product has no stock count.")
        return
    if exists:
        row.errors.append("Opening stock was already recorded for this product.")
        return
    if not row.quantity_blank and row.quantity is not None and row.quantity != current:
        row.errors.append(
            f"Opening quantity must equal the current stock ({current}). "
            "This import does not change the stock number."
        )
        return
    if row.errors:
        return
    row.quantity = current
    row.action = "opening"
    row.summary = f"Opening stock {current}"


def _decide_count(row: ClassifiedRow, current: int | None) -> None:
    if current is None:
        row.errors.append("This product has no stock count.")
        return
    if row.quantity is None or row.errors:
        return
    row.counted = row.quantity
    delta = row.counted - current
    if delta == 0:
        row.action = "none"
        row.quantity = 0
        row.summary = f"Stock already matches ({current}). No movement."
        return
    row.quantity = delta
    row.action = "adjustment"
    row.summary = f"Stock count {current} → {row.counted} ({delta:+d})"


async def _resolve_target(
    db: AsyncSession,
    product_id: uuid.UUID | None,
    sku: str,
    variant_id: uuid.UUID | None,
) -> tuple[Product | None, ProductVariant | None, list[str]]:
    errors: list[str] = []
    product: Product | None = None
    variant: ProductVariant | None = None
    if variant_id is not None:
        variant = await db.get(ProductVariant, variant_id)
        if variant is None:
            errors.append("No variant matches this variant_id.")
        else:
            product = await db.get(Product, variant.product_id)
    if sku:
        found = (
            await db.scalars(
                select(ProductVariant).where(
                    func.lower(ProductVariant.sku) == sku.lower(),
                    ProductVariant.sku != "",
                )
            )
        ).all()
        if not found:
            errors.append("No variant matches this SKU.")
        elif len(found) > 1:
            errors.append("More than one variant uses this SKU.")
        else:
            matched = found[0]
            if variant is not None and matched.id != variant.id:
                errors.append("This SKU belongs to a different variant than variant_id.")
            elif product is not None and matched.product_id != product.id:
                errors.append("This SKU belongs to a different product than product_id.")
            else:
                variant = matched
                owner = await db.get(Product, matched.product_id)
                if product is not None and owner is not None and owner.id != product.id:
                    errors.append("This SKU belongs to a different product than product_id.")
                product = owner
    if product_id is not None:
        named = await db.get(Product, product_id)
        if named is None:
            errors.append("No product matches this product_id.")
        elif product is not None and named.id != product.id:
            errors.append("product_id does not match the SKU or variant_id.")
        else:
            product = named
    if product is None:
        if not errors:
            errors.append("Enter a product_id or a sku. Products are never matched by name.")
        return None, None, errors
    if product.has_variants and variant is None:
        errors.append(
            "This product tracks stock per option. Enter the variant_id or the variant sku."
        )
    if variant is not None and not product.has_variants:
        errors.append("This product has no options. Remove the variant_id.")
    if variant is not None and variant.product_id != product.id:
        errors.append("This variant does not belong to the product.")
    return product, variant, errors


def _identity_error(row: ClassifiedRow) -> bool:
    prefixes = (
        "Enter a product",
        "No product",
        "No variant",
        "This SKU",
        "This product",
        "This variant",
        "product_id",
        "variant_id",
    )
    return any(message.startswith(prefixes) for message in row.errors)


async def _locked_quantity(
    db: AsyncSession, product_id: uuid.UUID, variant_id: uuid.UUID | None
) -> int | None:
    if variant_id is not None:
        variant = await db.get(ProductVariant, variant_id, populate_existing=True)
        return variant.quantity if variant is not None else None
    product = await db.get(Product, product_id, populate_existing=True)
    return product.quantity if product is not None else None


def _require_bucket(product: Product, variant: ProductVariant | None) -> None:
    if product.has_variants and variant is None:
        raise UnprocessableError(
            "This product tracks stock per option. Enter the variant_id or the variant sku."
        )
    if variant is not None and (not product.has_variants or variant.product_id != product.id):
        raise UnprocessableError("This variant does not belong to the product.")


async def _lock_products(db: AsyncSession, product_ids: list[uuid.UUID]) -> None:
    for product_id in product_ids:
        await db.execute(select(Product.id).where(Product.id == product_id).with_for_update())


async def _load_bucket(db: AsyncSession, product_id: uuid.UUID) -> _Bucket:
    product = await db.get(Product, product_id, populate_existing=True)
    if product is None:
        raise NotFoundError("Product not found")
    variants = (
        await db.scalars(select(ProductVariant).where(ProductVariant.product_id == product.id))
    ).all()
    quantities = {row.id: row.quantity for row in variants}
    return _Bucket(
        product_id=product.id,
        has_variants=product.has_variants,
        cost=product.cost_price,
        quantity=product.quantity,
        status=product.status,
        variants=dict(quantities),
        original_cost=product.cost_price,
        original_quantity=product.quantity,
        original_status=product.status,
        original_variants=dict(quantities),
    )


def _apply_receipt(
    bucket: _Bucket, variant_id: uuid.UUID | None, quantity: int, unit_cost: Decimal
) -> None:
    old = _bucket_qty(bucket, variant_id)
    bucket.cost = weighted_average_cost(old, bucket.cost, quantity, unit_cost)
    if old is None:
        return
    _set_bucket_qty(bucket, variant_id, old + quantity)


def _bucket_qty(bucket: _Bucket, variant_id: uuid.UUID | None) -> int | None:
    if variant_id is None:
        return bucket.quantity
    return bucket.variants.get(variant_id)


def _set_bucket_qty(bucket: _Bucket, variant_id: uuid.UUID | None, quantity: int) -> None:
    if variant_id is None:
        bucket.quantity = quantity
        return
    bucket.variants[variant_id] = quantity


async def _persist_bucket(db: AsyncSession, bucket: _Bucket, actor_id: uuid.UUID | None) -> None:
    product = await db.get(Product, bucket.product_id)
    if product is not None:
        db.expire(product)
    variant_changes: list[dict[str, object]] = []
    if bucket.has_variants:
        for variant_id, quantity in bucket.variants.items():
            original = bucket.original_variants.get(variant_id)
            if quantity == original:
                continue
            cached = await db.get(ProductVariant, variant_id)
            if cached is not None:
                db.expire(cached)
            await db.execute(
                update(ProductVariant)
                .where(ProductVariant.id == variant_id)
                .values(quantity=quantity, updated_at=func.now())
            )
            variant_changes.append(
                {"variant_id": str(variant_id), "from": original, "to": quantity}
            )
        await db.execute(
            update(Product)
            .where(Product.id == bucket.product_id)
            .values(cost_price=bucket.cost, updated_at=func.now())
        )
        if variant_changes:
            await variant_service.rollup_by_id(db, bucket.product_id)
        fresh = await db.get(Product, bucket.product_id, populate_existing=not variant_changes)
    else:
        values: dict[str, object] = {"cost_price": bucket.cost, "updated_at": func.now()}
        if bucket.quantity is not None:
            values["quantity"] = bucket.quantity
            new_status = _status_after(bucket.status, bucket.quantity)
            if new_status is not None:
                values["status"] = new_status
        await db.execute(update(Product).where(Product.id == bucket.product_id).values(**values))
        fresh = await db.get(Product, bucket.product_id, populate_existing=True)
    if fresh is None:
        raise NotFoundError("Product not found")
    await _audit_bucket(db, actor_id, bucket, fresh, variant_changes)


def _status_after(current: str, new_qty: int | None) -> str | None:
    if new_qty == 0 and current == StockStatus.AVAILABLE.value:
        return StockStatus.SOLD_OUT.value
    if new_qty is not None and new_qty > 0 and current == StockStatus.SOLD_OUT.value:
        return StockStatus.AVAILABLE.value
    return None


async def _audit_bucket(
    db: AsyncSession,
    actor_id: uuid.UUID | None,
    bucket: _Bucket,
    fresh: Product,
    variant_changes: list[dict[str, object]],
) -> None:
    stock: dict[str, object] = {}
    if fresh.quantity != bucket.original_quantity:
        stock["quantity"] = {"from": bucket.original_quantity, "to": fresh.quantity}
    if fresh.status != bucket.original_status:
        stock["status"] = {"from": bucket.original_status, "to": fresh.status}
    if variant_changes:
        stock["variants"] = variant_changes
    if stock:
        await audit_service.record(
            db,
            actor_id=actor_id,
            action=AuditAction.PRODUCT_STOCK_UPDATED,
            target_type="product",
            target_id=fresh.id,
            metadata=stock,
        )
    if fresh.cost_price != bucket.original_cost:
        await audit_service.record(
            db,
            actor_id=actor_id,
            action=AuditAction.PRODUCT_PRICE_UPDATED,
            target_type="product",
            target_id=fresh.id,
            metadata={
                "cost_price": {
                    "from": _money_text(bucket.original_cost),
                    "to": _money_text(fresh.cost_price),
                }
            },
        )
    telegram_notify.note_low_stock(
        db,
        product_id=fresh.id,
        title=fresh.title,
        before=bucket.original_quantity,
        after=fresh.quantity,
    )


async def _opening_exists(
    db: AsyncSession, product_id: uuid.UUID, variant_id: uuid.UUID | None
) -> bool:
    filters = [
        StockMovement.movement_type == MovementType.OPENING.value,
        StockMovement.product_id == product_id,
    ]
    if variant_id is None:
        filters.append(StockMovement.variant_id.is_(None))
    else:
        filters.append(StockMovement.variant_id == variant_id)
    found = await db.scalar(select(StockMovement.id).where(*filters).limit(1))
    return found is not None


async def _product_cost(db: AsyncSession, product_id: uuid.UUID) -> Decimal | None:
    product = await db.get(Product, product_id)
    return product.cost_price if product is not None else None


async def _hash_seen(db: AsyncSession, digest: str) -> bool:
    found = await db.scalar(select(ImportBatch.id).where(ImportBatch.file_hash == digest).limit(1))
    return found is not None


async def _supplier_counts(db: AsyncSession, names: list[str]) -> dict[str, int]:
    unique = sorted(set(names))
    if not unique:
        return {}
    rows = (
        await db.execute(
            select(Supplier.name, func.count())
            .where(Supplier.name.in_(unique))
            .group_by(Supplier.name)
        )
    ).all()
    return {str(name): int(count) for name, count in rows}


async def _suppliers_for_import(
    db: AsyncSession, rows: list[ClassifiedRow]
) -> dict[str, uuid.UUID]:
    names = sorted({row.supplier_name for row in rows if row.supplier_name})
    found = (
        await db.scalars(
            select(Supplier).where(Supplier.name.in_(names)).order_by(Supplier.created_at)
        )
    ).all()
    mapped: dict[str, uuid.UUID] = {}
    for supplier in found:
        mapped.setdefault(supplier.name, supplier.id)
    first_by_name: dict[str, ClassifiedRow] = {}
    for row in rows:
        first_by_name.setdefault(row.supplier_name, row)
    for name, row in first_by_name.items():
        if name in mapped:
            continue
        supplier = Supplier(
            id=uuid.uuid4(),
            name=name,
            phone=row.supplier_phone,
            address=row.supplier_address,
            note=row.supplier_note,
        )
        db.add(supplier)
        mapped[name] = supplier.id
    return mapped


async def _export_products(db: AsyncSession, query: DateRangeQuery) -> bytes:
    stmt = select(Product).order_by(Product.title, Product.id)
    if query.date_from is not None:
        stmt = stmt.where(Product.updated_at >= _day_start(query.date_from))
    if query.date_to is not None:
        stmt = stmt.where(Product.updated_at < _day_end(query.date_to))
    products = (await db.scalars(stmt.limit(MAX_EXPORT_ROWS + 1))).all()
    _cap(len(products))
    variants = await _variants_for(db, [row.id for row in products])
    exported: list[list[object]] = []
    for product in products:
        own = variants.get(product.id, [])
        if product.has_variants and own:
            for variant in own:
                exported.append(
                    [
                        str(product.id),
                        str(variant.id),
                        variant.sku,
                        product.title,
                        variant.quantity,
                        product.cost_price,
                        product.status,
                        product.updated_at,
                    ]
                )
        else:
            exported.append(
                [
                    str(product.id),
                    "",
                    "",
                    product.title,
                    product.quantity,
                    product.cost_price,
                    product.status,
                    product.updated_at,
                ]
            )
    _cap(len(exported))
    return workbook_bytes(list(PRODUCT_EXPORT_COLUMNS), exported, "Products")


async def _export_purchases(db: AsyncSession, query: DateRangeQuery) -> bytes:
    stmt = (
        select(Purchase)
        .where(*_purchase_filters(query))
        .options(selectinload(Purchase.items))
        .order_by(Purchase.purchased_on.desc(), Purchase.id)
        .limit(MAX_EXPORT_ROWS + 1)
    )
    purchases = (await db.scalars(stmt)).all()
    _cap(len(purchases))
    names = await _supplier_names(db, [row.supplier_id for row in purchases])
    variant_ids = [
        item.variant_id
        for purchase in purchases
        for item in purchase.items
        if item.variant_id
    ]
    skus = await _skus(db, variant_ids)
    exported: list[list[object]] = []
    for purchase in purchases:
        for item in purchase.items:
            exported.append(
                [
                    str(purchase.id),
                    purchase.purchased_on,
                    purchase.invoice_no,
                    names.get(purchase.supplier_id, ""),
                    str(item.product_id) if item.product_id else "",
                    str(item.variant_id) if item.variant_id else "",
                    skus.get(item.variant_id, "") if item.variant_id else "",
                    item.quantity,
                    item.unit_cost,
                ]
            )
    _cap(len(exported))
    return workbook_bytes(list(PURCHASE_EXPORT_COLUMNS), exported, "Purchases")


async def _export_movements(db: AsyncSession, query: DateRangeQuery) -> bytes:
    movement_query = MovementQuery(
        date_from=query.date_from, date_to=query.date_to, page=1, page_size=1
    )
    stmt = (
        select(StockMovement)
        .where(*_movement_filters(movement_query))
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .limit(MAX_EXPORT_ROWS + 1)
    )
    rows = (await db.scalars(stmt)).all()
    _cap(len(rows))
    skus = await _skus(db, [row.variant_id for row in rows if row.variant_id])
    exported = [
        [
            str(row.id),
            row.created_at,
            row.movement_type,
            str(row.product_id) if row.product_id else "",
            str(row.variant_id) if row.variant_id else "",
            skus.get(row.variant_id, "") if row.variant_id else "",
            row.quantity,
            row.unit_cost,
            str(row.order_id) if row.order_id else "",
            str(row.purchase_id) if row.purchase_id else "",
            str(row.import_batch_id) if row.import_batch_id else "",
            str(row.actor_id) if row.actor_id else "",
            row.note,
        ]
        for row in rows
    ]
    return workbook_bytes(list(MOVEMENT_EXPORT_COLUMNS), exported, "Movements")


def _purchase_filters(query: PurchaseQuery | DateRangeQuery) -> list[_Expr]:
    filters: list[_Expr] = []
    if query.date_from is not None:
        filters.append(Purchase.purchased_on >= query.date_from)
    if query.date_to is not None:
        filters.append(Purchase.purchased_on <= query.date_to)
    supplier_id = getattr(query, "supplier_id", None)
    if supplier_id is not None:
        filters.append(Purchase.supplier_id == supplier_id)
    return filters


def _movement_filters(query: MovementQuery) -> list[_Expr]:
    filters: list[_Expr] = []
    if query.product_id is not None:
        filters.append(StockMovement.product_id == query.product_id)
    if query.movement_type is not None:
        filters.append(StockMovement.movement_type == query.movement_type.value)
    if query.date_from is not None:
        filters.append(StockMovement.created_at >= _day_start(query.date_from))
    if query.date_to is not None:
        filters.append(StockMovement.created_at < _day_end(query.date_to))
    return filters


def _day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _day_end(day: date) -> datetime:
    return _day_start(day + timedelta(days=1))


def _cap(count: int) -> None:
    if count > MAX_EXPORT_ROWS:
        raise UnprocessableError(
            "Narrow the date range. An export can contain at most 20000 rows."
        )


def _contains(term: str) -> str:
    escaped = term.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _safe_name(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1].strip()[:255]


def _preview_row(row: ClassifiedRow) -> ImportPreviewRow:
    return ImportPreviewRow(
        row=row.number,
        valid=row.valid,
        action=row.action if row.valid else "none",
        errors=list(row.errors),
        summary=row.summary if row.valid else "",
    )


async def _count(
    db: AsyncSession,
    model: type[Supplier] | type[Purchase] | type[StockMovement],
    filters: Sequence[_Expr],
) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*filters)) or 0)


async def _supplier(db: AsyncSession, supplier_id: uuid.UUID) -> Supplier:
    row = await db.get(Supplier, supplier_id)
    if row is None:
        raise NotFoundError("Supplier not found")
    return row


async def _purchase(db: AsyncSession, purchase_id: uuid.UUID) -> Purchase:
    row = (
        await db.scalars(
            select(Purchase)
            .where(Purchase.id == purchase_id)
            .options(selectinload(Purchase.items))
        )
    ).first()
    if row is None:
        raise NotFoundError("Purchase not found")
    return row


def _supplier_read(row: Supplier) -> SupplierRead:
    return SupplierRead(
        id=row.id,
        name=row.name,
        phone=row.phone,
        address=row.address,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _purchase_read(row: Purchase, supplier_name: str) -> PurchaseRead:
    return PurchaseRead(
        id=row.id,
        supplier_id=row.supplier_id,
        supplier_name=supplier_name,
        purchased_on=row.purchased_on,
        invoice_no=row.invoice_no,
        note=row.note,
        created_at=row.created_at,
        items=[
            PurchaseItemRead(
                id=item.id,
                product_id=item.product_id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
            )
            for item in row.items
        ],
    )


async def _supplier_names(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    unique = list(set(ids))
    if not unique:
        return {}
    rows = (await db.scalars(select(Supplier).where(Supplier.id.in_(unique)))).all()
    return {row.id: row.name for row in rows}


async def _movement_reads(
    db: AsyncSession, rows: Sequence[StockMovement]
) -> list[MovementRead]:
    product_ids = [row.product_id for row in rows if row.product_id is not None]
    products: dict[uuid.UUID, Product] = {}
    if product_ids:
        found = (await db.scalars(select(Product).where(Product.id.in_(set(product_ids))))).all()
        products = {item.id: item for item in found}
    skus = await _skus(db, [row.variant_id for row in rows if row.variant_id is not None])
    reads: list[MovementRead] = []
    for row in rows:
        product = products.get(row.product_id) if row.product_id else None
        reads.append(
            MovementRead(
                id=row.id,
                product_id=row.product_id,
                variant_id=row.variant_id,
                product_title=product.title if product is not None else "",
                sku=skus.get(row.variant_id, "") if row.variant_id else "",
                quantity=row.quantity,
                movement_type=MovementType(row.movement_type),
                unit_cost=row.unit_cost,
                order_id=row.order_id,
                purchase_id=row.purchase_id,
                import_batch_id=row.import_batch_id,
                actor_id=row.actor_id,
                note=row.note,
                created_at=row.created_at,
            )
        )
    return reads


async def _variants_for(
    db: AsyncSession, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ProductVariant]]:
    if not product_ids:
        return {}
    rows = (
        await db.scalars(
            select(ProductVariant)
            .where(ProductVariant.product_id.in_(product_ids))
            .order_by(ProductVariant.sort_order, ProductVariant.id)
        )
    ).all()
    grouped: dict[uuid.UUID, list[ProductVariant]] = defaultdict(list)
    for row in rows:
        grouped[row.product_id].append(row)
    return grouped


async def _skus(db: AsyncSession, variant_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    unique = list(set(variant_ids))
    if not unique:
        return {}
    rows = (await db.scalars(select(ProductVariant).where(ProductVariant.id.in_(unique)))).all()
    return {row.id: row.sku for row in rows}
