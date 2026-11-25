"""Superadmin-only Steadfast finance & COD reconciliation service (Phase 24).

All operations are strictly superadmin-only (enforced at the endpoint layer via
``RequireSuperadmin``). Cross-matching uses batch queries (zero N+1), and COD
reconciliation is atomic and 100% idempotent (clicking reconcile twice never
double-counts ``order.paid_amount`` or ``due_amount``).
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditAction
from app.models.courier import CourierShipment
from app.models.order import ActivityAction, Order
from app.models.user import User
from app.schemas.courier import (
    ReconcileMatchedOrder,
    SteadfastBalanceResponse,
    SteadfastPaymentDetailResponse,
    SteadfastPaymentsListResponse,
    SteadfastReconcileResponse,
)
from app.services import audit_service, order_service
from app.services.courier.steadfast_client import SteadfastClient, steadfast_client

_PROVIDER = "steadfast"


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _str_or_none(val: Any) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text if text else None


def _int_money(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return max(val, 0)
    if isinstance(val, float):
        return max(int(round(val)), 0)
    if isinstance(val, str):
        cleaned = val.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return max(int(round(float(cleaned))), 0)
        except ValueError:
            return None
    return None


def _extract_payment_parcels(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract settled parcel rows from Steadfast's `/payments/{id}` response."""
    for key in ("consignments", "parcels", "orders", "items"):
        val = detail.get(key)
        if isinstance(val, list):
            return [row for row in val if isinstance(row, dict)]
    data = detail.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("consignments", "parcels", "orders", "items"):
            val = data.get(key)
            if isinstance(val, list):
                return [row for row in val if isinstance(row, dict)]
    payment = detail.get("payment")
    if isinstance(payment, dict):
        for key in ("consignments", "parcels", "orders", "items"):
            val = payment.get(key)
            if isinstance(val, list):
                return [row for row in val if isinstance(row, dict)]
    return []


def _parcel_settled_amount(
    parcel: dict[str, Any],
    shipment: CourierShipment | None,
    order: Order,
) -> int:
    for key in (
        "cod_amount",
        "collected_amount",
        "cash_collection",
        "amount",
        "payable_amount",
    ):
        parsed = _int_money(parcel.get(key))
        if parsed is not None:
            return parsed
    if shipment is not None and shipment.cod_amount > 0:
        return int(shipment.cod_amount)
    paid_before = order_service.effective_paid(order)
    return max(int(order.total) - paid_before, 0)


async def get_balance(
    *, client: SteadfastClient = steadfast_client
) -> SteadfastBalanceResponse:
    raw = await client.get_balance()
    bal_raw = raw.get("current_balance")
    balance: float | None = None
    if isinstance(bal_raw, (int, float)) and not isinstance(bal_raw, bool):
        balance = float(bal_raw)
    elif isinstance(bal_raw, str):
        try:
            balance = float(bal_raw.strip())
        except ValueError:
            balance = None
    return SteadfastBalanceResponse(current_balance=balance, raw=raw)


async def list_payments(
    *,
    page: int = 1,
    page_size: int = 20,
    client: SteadfastClient = steadfast_client,
) -> SteadfastPaymentsListResponse:
    all_items = await client.list_payments()
    total = len(all_items)
    pages = math.ceil(total / page_size) if total > 0 else 0
    start = (page - 1) * page_size
    end = start + page_size
    return SteadfastPaymentsListResponse(
        items=all_items[start:end],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def _cross_match_parcels(
    db: AsyncSession,
    parcels: list[dict[str, Any]],
) -> tuple[
    list[tuple[dict[str, Any], CourierShipment | None, Order, int]],
    list[dict[str, Any]],
]:
    """Batch-load shipments & orders for every parcel in the payment (zero N+1)."""
    cids: set[str] = set()
    invoices: set[str] = set()
    for p in parcels:
        cid = _str_or_none(p.get("consignment_id"))
        inv = _str_or_none(p.get("invoice"))
        if cid:
            cids.add(cid)
        if inv:
            invoices.add(inv)

    shipments_by_cid: dict[str, CourierShipment] = {}
    shipments_by_invoice: dict[str, CourierShipment] = {}
    if cids or invoices:
        conds = []
        if cids:
            conds.append(CourierShipment.consignment_id.in_(cids))
        if invoices:
            conds.append(CourierShipment.invoice.in_(invoices))
        ship_rows = (
            await db.scalars(
                select(CourierShipment)
                .where(CourierShipment.provider == _PROVIDER, or_(*conds))
                .order_by(CourierShipment.created_at.desc(), CourierShipment.id.desc())
            )
        ).all()
        for s in ship_rows:
            if s.consignment_id and s.consignment_id not in shipments_by_cid:
                shipments_by_cid[s.consignment_id] = s
            if s.invoice and s.invoice not in shipments_by_invoice:
                shipments_by_invoice[s.invoice] = s

    order_ids: set[uuid.UUID] = {
        s.order_id
        for s in (*shipments_by_cid.values(), *shipments_by_invoice.values())
        if s.order_id is not None
    }
    orders_by_id: dict[uuid.UUID, Order] = {}
    orders_by_number: dict[str, Order] = {}
    if order_ids or invoices:
        oconds = []
        if order_ids:
            oconds.append(Order.id.in_(order_ids))
        if invoices:
            oconds.append(Order.number.in_(invoices))
        order_rows = (await db.scalars(select(Order).where(or_(*oconds)))).all()
        for o in order_rows:
            orders_by_id[o.id] = o
            orders_by_number[o.number] = o

    matched: list[tuple[dict[str, Any], CourierShipment | None, Order, int]] = []
    unmatched: list[dict[str, Any]] = []
    seen_order_ids: set[uuid.UUID] = set()

    for p in parcels:
        cid = _str_or_none(p.get("consignment_id"))
        inv = _str_or_none(p.get("invoice"))
        shipment = (
            (shipments_by_cid.get(cid) if cid else None)
            or (shipments_by_invoice.get(inv) if inv else None)
        )
        order = (
            (orders_by_id.get(shipment.order_id) if shipment and shipment.order_id else None)
            or (orders_by_number.get(inv) if inv else None)
        )
        if order is None:
            unmatched.append(p)
            continue
        if order.id in seen_order_ids:
            continue
        seen_order_ids.add(order.id)
        settled_amount = _parcel_settled_amount(p, shipment, order)
        matched.append((p, shipment, order, settled_amount))

    return matched, unmatched


async def get_payment_detail(
    db: AsyncSession,
    payment_id: str,
    *,
    client: SteadfastClient = steadfast_client,
) -> SteadfastPaymentDetailResponse:
    raw = await client.get_payment_detail(payment_id)
    parcels = _extract_payment_parcels(raw)
    matched_rows, unmatched = await _cross_match_parcels(db, parcels)

    matched_items: list[ReconcileMatchedOrder] = []
    already_count = 0
    pending_count = 0

    for parcel, shipment, order, settled_amount in matched_rows:
        paid_before = order_service.effective_paid(order)
        due_before = max(int(order.total) - paid_before, 0)
        already = bool(shipment is not None and shipment.settled_payment_id)
        if already:
            already_count += 1
        else:
            pending_count += 1
        matched_items.append(
            ReconcileMatchedOrder(
                order_id=order.id,
                order_number=order.number,
                shipment_id=shipment.id if shipment is not None else None,
                consignment_id=(
                    (shipment.consignment_id if shipment is not None else None)
                    or _str_or_none(parcel.get("consignment_id"))
                ),
                order_total=int(order.total),
                paid_before=paid_before,
                due_before=due_before,
                settled_amount=settled_amount,
                already_reconciled=already,
                settled_payment_id=shipment.settled_payment_id if shipment else None,
            )
        )

    return SteadfastPaymentDetailResponse(
        payment=raw,
        matched_orders=matched_items,
        unmatched_parcels=unmatched,
        already_reconciled_count=already_count,
        pending_reconcile_count=pending_count,
    )


async def reconcile_payment(
    db: AsyncSession,
    payment_id: str,
    *,
    actor: User,
    client: SteadfastClient = steadfast_client,
) -> SteadfastReconcileResponse:
    raw = await client.get_payment_detail(payment_id)
    parcels = _extract_payment_parcels(raw)
    matched_rows, unmatched = await _cross_match_parcels(db, parcels)

    now = _now_utc()
    pid_str = str(payment_id).strip()[:64]
    reconciled_count = 0
    already_count = 0
    total_applied = 0
    matched_items: list[ReconcileMatchedOrder] = []
    reconciled_order_numbers: list[str] = []

    for parcel, shipment, order, settled_amount in matched_rows:
        paid_before = order_service.effective_paid(order)
        due_before = max(int(order.total) - paid_before, 0)

        if shipment is not None and shipment.settled_payment_id:
            already_count += 1
            matched_items.append(
                ReconcileMatchedOrder(
                    order_id=order.id,
                    order_number=order.number,
                    shipment_id=shipment.id,
                    consignment_id=shipment.consignment_id,
                    order_total=int(order.total),
                    paid_before=paid_before,
                    due_before=due_before,
                    settled_amount=shipment.settled_amount or settled_amount,
                    already_reconciled=True,
                    settled_payment_id=shipment.settled_payment_id,
                )
            )
            continue

        cid = _str_or_none(parcel.get("consignment_id"))
        if shipment is None:
            shipment = CourierShipment(
                order_id=order.id,
                provider=_PROVIDER,
                invoice=order.number,
                consignment_id=cid,
                tracking_code=order.tracking_number or "",
                cod_amount=settled_amount,
                delivery_status="delivered",
                is_final=True,
            )
            db.add(shipment)
            await db.flush()

        shipment.settled_payment_id = pid_str
        shipment.settled_amount = settled_amount
        shipment.settled_at = now

        applied = 0
        if due_before > 0 and settled_amount > 0:
            new_paid = min(paid_before + settled_amount, int(order.total))
            applied = max(new_paid - paid_before, 0)
            new_due = max(int(order.total) - new_paid, 0)
            order.paid_amount = new_paid
            order.due_amount = new_due
            order_service.log_activity(
                db,
                order.id,
                actor.id,
                ActivityAction.PAYMENT_UPDATED,
                f"Steadfast COD reconciled (Payment #{pid_str}: ৳{applied})",
                {
                    "provider": _PROVIDER,
                    "payment_id": pid_str,
                    "consignment_id": shipment.consignment_id,
                    "from_paid": paid_before,
                    "to_paid": new_paid,
                    "due_amount": new_due,
                    "settled_amount": settled_amount,
                },
            )

        reconciled_count += 1
        total_applied += applied
        reconciled_order_numbers.append(order.number)
        matched_items.append(
            ReconcileMatchedOrder(
                order_id=order.id,
                order_number=order.number,
                shipment_id=shipment.id,
                consignment_id=shipment.consignment_id,
                order_total=int(order.total),
                paid_before=paid_before,
                due_before=due_before,
                settled_amount=settled_amount,
                already_reconciled=False,
                settled_payment_id=pid_str,
            )
        )

    if reconciled_count > 0:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.COURIER_COD_RECONCILED,
            target_type="courier_payment",
            target_id=pid_str,
            metadata={
                "provider": _PROVIDER,
                "payment_id": pid_str,
                "reconciled_count": reconciled_count,
                "already_reconciled_count": already_count,
                "unmatched_count": len(unmatched),
                "total_amount_applied": total_applied,
                "order_numbers": reconciled_order_numbers[:100],
            },
        )
        await db.commit()

    return SteadfastReconcileResponse(
        payment_id=pid_str,
        reconciled_count=reconciled_count,
        already_reconciled_count=already_count,
        unmatched_count=len(unmatched),
        total_amount_applied=total_applied,
        matched_orders=matched_items,
        unmatched_parcels=unmatched,
    )
