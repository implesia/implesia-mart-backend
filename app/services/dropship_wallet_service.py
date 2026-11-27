"""Atomic double-entry wallet ledger, T+3 unlock, RTO deduction, payouts & top-ups."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.models.audit_event import AuditAction
from app.models.courier import CourierShipment
from app.models.dropshipping import (
    DropshipperPayoutRequest,
    DropshipperProfile,
    DropshipperStatus,
    DropshipperTier,
    DropshipperTopupRequest,
    DropshipperWalletTransaction,
    DropshippingSettings,
    PayoutMethod,
    PayoutRequestStatus,
    RtoChargeMode,
    TopupRequestStatus,
    WalletBucket,
    WalletEntryType,
)
from app.models.order import Order
from app.models.user import User
from app.schemas.common import page_count
from app.schemas.dropshipping import (
    AdminDropshipperPayoutListResponse,
    AdminDropshipperPayoutRead,
    AdminDropshipperTopupListResponse,
    AdminDropshipperTopupRead,
    AdminPayoutMarkPaidRequest,
    AdminPayoutRejectRequest,
    AdminTopupApproveRequest,
    AdminTopupRejectRequest,
    AdminWalletAdjustRequest,
    DropshipperPayoutCreateRequest,
    DropshipperPayoutListResponse,
    DropshipperPayoutRead,
    DropshipperProfileRead,
    DropshipperTopupCreateRequest,
    DropshipperTopupListResponse,
    DropshipperTopupRead,
    DropshipperWalletSummary,
    DropshipperWalletTransactionListResponse,
    DropshipperWalletTransactionRead,
)
from app.services import audit_service, dropshipping_service, notification_service

ACTIVE_DROPSHIP_ORDER_STATUSES = ("new", "confirmed", "packed", "shipped")


def _is_sqlite(db: AsyncSession) -> bool:
    try:
        bind = db.get_bind()
        return bind is not None and bind.dialect.name == "sqlite"
    except Exception:
        return True


def _utc_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def _get_settings(db: AsyncSession) -> DropshippingSettings:
    """Read singleton settings without committing (safe inside outer transactions)."""
    row = await db.get(DropshippingSettings, 1)
    if row is None:
        return DropshippingSettings(
            id=1,
            enabled=True,
            registration_fee=0,
            new_seller_max_active_orders=3,
            trusted_delivery_threshold=5,
            negative_wallet_limit=-200,
            payout_unlock_days=3,
            require_cod_reconciled=False,
            min_withdrawal_amount=500,
            rto_charge_mode=RtoChargeMode.ORDER_SHIPPING.value,
            rto_fixed_fee=130,
            platform_fee_percent=0,
            packaging_fee_flat=0,
        )
    return row


async def _lock_profile_by_user(
    db: AsyncSession, user_id: uuid.UUID
) -> DropshipperProfile | None:
    stmt = select(DropshipperProfile).where(DropshipperProfile.user_id == user_id)
    if not _is_sqlite(db):
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lock_profile_by_id(
    db: AsyncSession, profile_id: uuid.UUID
) -> DropshipperProfile | None:
    stmt = select(DropshipperProfile).where(DropshipperProfile.id == profile_id)
    if not _is_sqlite(db):
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _insert_ledger_tx(
    db: AsyncSession, tx: DropshipperWalletTransaction
) -> bool:
    """Insert a wallet ledger row idempotently. Returns False if idempotency_key already exists."""
    existing = await db.scalar(
        select(DropshipperWalletTransaction.id).where(
            DropshipperWalletTransaction.idempotency_key == tx.idempotency_key
        )
    )
    if existing is not None:
        return False
    try:
        async with db.begin_nested():
            db.add(tx)
            await db.flush()
        return True
    except IntegrityError:
        return False


def _tx_to_read(tx: DropshipperWalletTransaction) -> DropshipperWalletTransactionRead:
    return DropshipperWalletTransactionRead(
        id=tx.id,
        order_id=tx.order_id,
        payout_id=tx.payout_id,
        topup_id=tx.topup_id,
        entry_type=WalletEntryType(tx.entry_type),
        amount=tx.amount,
        balance_bucket=WalletBucket(tx.balance_bucket),
        unlock_at=tx.unlock_at,
        unlocked_at=tx.unlocked_at,
        note=tx.note,
        created_at=tx.created_at,
    )


def _payout_to_read(payout: DropshipperPayoutRequest) -> DropshipperPayoutRead:
    return DropshipperPayoutRead(
        id=payout.id,
        dropshipper_id=payout.dropshipper_id,
        amount=payout.amount,
        status=PayoutRequestStatus(payout.status),
        payout_method=PayoutMethod(payout.payout_method),
        payout_account_number=payout.payout_account_number,
        payout_account_name=payout.payout_account_name,
        bank_name=payout.bank_name,
        bank_branch=payout.bank_branch,
        transaction_id=payout.transaction_id,
        admin_note=payout.admin_note,
        processed_at=payout.processed_at,
        created_at=payout.created_at,
        updated_at=payout.updated_at,
    )


def _topup_to_read(topup: DropshipperTopupRequest) -> DropshipperTopupRead:
    return DropshipperTopupRead(
        id=topup.id,
        dropshipper_id=topup.dropshipper_id,
        amount=topup.amount,
        payment_method=topup.payment_method,
        sender_number=topup.sender_number,
        transaction_id=topup.transaction_id,
        status=TopupRequestStatus(topup.status),
        admin_note=topup.admin_note,
        processed_at=topup.processed_at,
        created_at=topup.created_at,
        updated_at=topup.updated_at,
    )


async def count_active_dropship_orders(db: AsyncSession, dropshipper_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count(Order.id)).where(
            Order.dropshipper_id == dropshipper_id,
            Order.status.in_(ACTIVE_DROPSHIP_ORDER_STATUSES),
        )
    )
    return int(count or 0)


# ---------------------------------------------------------------------------
# Automated Order Lifecycle Financial Hooks (Non-committing; caller commits)
# ---------------------------------------------------------------------------


async def on_dropship_order_delivered(db: AsyncSession, order: Order) -> bool:
    """Credit pending profit, increment delivered_count, and auto-promote tier.

    Idempotent via ``order:{order.id}:delivered_credit``. Does NOT commit.
    """
    if order.dropshipper_id is None:
        return False

    profile = await _lock_profile_by_user(db, order.dropshipper_id)
    if profile is None:
        return False

    settings = await _get_settings(db)
    profit = int(order.dropship_profit_amount or 0)
    delivered_at = _utc_aware(order.delivered_at) if order.delivered_at else datetime.now(UTC)
    unlock_at = delivered_at + timedelta(days=settings.payout_unlock_days)

    tx = DropshipperWalletTransaction(
        dropshipper_id=order.dropshipper_id,
        order_id=order.id,
        entry_type=WalletEntryType.CREDIT_PENDING.value,
        amount=profit,
        balance_bucket=WalletBucket.PENDING.value,
        unlock_at=unlock_at,
        unlocked_at=None,
        idempotency_key=f"order:{order.id}:delivered_credit",
        note=(
            f"Profit ৳{profit} credited (pending T+{settings.payout_unlock_days}d unlock) "
            f"for delivered order #{order.number}"
        ),
    )
    inserted = await _insert_ledger_tx(db, tx)
    if not inserted:
        return False

    profile.pending_balance += profit
    profile.delivered_count += 1
    if profit > 0:
        profile.total_earned += profit

    promoted = False
    if (
        profile.tier == DropshipperTier.NEW.value
        and profile.delivered_count >= settings.trusted_delivery_threshold
    ):
        profile.tier = DropshipperTier.TRUSTED.value
        promoted = True

    await db.flush()

    msg = (
        f"Order #{order.number} delivered! ৳{profit} profit added to your pending balance "
        f"(unlocks in {settings.payout_unlock_days} day(s))."
    )
    if promoted:
        msg += " Congratulations — you have been promoted to Trusted Seller tier!"

    await notification_service.create_dropshipper_notification(
        db,
        order.dropshipper_id,
        title=f"Profit Credited: ৳{profit}",
        message=msg,
        notif_type="dropshipper_delivered",
        order_id=order.id,
        order_number=order.number,
        url="/dropshipper/wallet",
        commit=False,
    )
    return True


async def on_dropship_order_returned(db: AsyncSession, order: Order) -> bool:
    """Debit RTO shipping charge from available_balance and reverse any pending profit.

    Idempotent via ``order:{order.id}:rto_debit`` & ``order:{order.id}:pending_reversal``.
    Does NOT commit.
    """
    if order.dropshipper_id is None:
        return False

    profile = await _lock_profile_by_user(db, order.dropshipper_id)
    if profile is None:
        return False

    settings = await _get_settings(db)
    rto_fee = (
        int(order.shipping or 0)
        if settings.rto_charge_mode == RtoChargeMode.ORDER_SHIPPING.value
        else int(settings.rto_fixed_fee)
    )
    now = datetime.now(UTC)

    rto_tx = DropshipperWalletTransaction(
        dropshipper_id=order.dropshipper_id,
        order_id=order.id,
        entry_type=WalletEntryType.DEBIT_RTO.value,
        amount=-rto_fee,
        balance_bucket=WalletBucket.AVAILABLE.value,
        idempotency_key=f"order:{order.id}:rto_debit",
        note=f"RTO shipping fee ৳{rto_fee} deducted for returned order #{order.number}",
    )
    rto_inserted = await _insert_ledger_tx(db, rto_tx)
    if rto_inserted:
        profile.available_balance -= rto_fee
        profile.returned_count += 1

    # Reverse any un-unlocked pending profit credit if the order was delivered then returned
    pending_tx = (
        await db.execute(
            select(DropshipperWalletTransaction).where(
                DropshipperWalletTransaction.order_id == order.id,
                DropshipperWalletTransaction.entry_type == WalletEntryType.CREDIT_PENDING.value,
                DropshipperWalletTransaction.unlocked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if pending_tx is not None:
        reversal_tx = DropshipperWalletTransaction(
            dropshipper_id=order.dropshipper_id,
            order_id=order.id,
            entry_type=WalletEntryType.DEBIT_RTO.value,
            amount=-pending_tx.amount,
            balance_bucket=WalletBucket.PENDING.value,
            idempotency_key=f"order:{order.id}:pending_reversal",
            note=f"Pending profit reversed for returned order #{order.number}",
        )
        if await _insert_ledger_tx(db, reversal_tx):
            pending_tx.unlocked_at = now
            profile.pending_balance -= pending_tx.amount
            if pending_tx.amount > 0:
                profile.total_earned = max(0, profile.total_earned - pending_tx.amount)

    await db.flush()

    if rto_inserted:
        await notification_service.create_dropshipper_notification(
            db,
            order.dropshipper_id,
            title=f"RTO Fee Deducted: ৳{rto_fee}",
            message=(
                f"Order #{order.number} was returned. ৳{rto_fee} RTO fee has been deducted "
                f"from your available balance (current: ৳{profile.available_balance})."
            ),
            notif_type="dropshipper_rto",
            order_id=order.id,
            order_number=order.number,
            url="/dropshipper/wallet",
            commit=False,
        )
    return rto_inserted


async def settle_matured_pending_profits(
    db: AsyncSession,
    dropshipper_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Unlock matured pending profits into available_balance (automatically offsetting negative).

    Idempotent via ``unlock:{pending_tx.id}``. Does NOT commit.
    """
    profile = await _lock_profile_by_user(db, dropshipper_id)
    if profile is None:
        return 0

    settings = await _get_settings(db)
    current_time = _utc_aware(now) if now is not None else datetime.now(UTC)

    pending_rows = (
        await db.scalars(
            select(DropshipperWalletTransaction)
            .where(
                DropshipperWalletTransaction.dropshipper_id == dropshipper_id,
                DropshipperWalletTransaction.entry_type == WalletEntryType.CREDIT_PENDING.value,
                DropshipperWalletTransaction.unlocked_at.is_(None),
                DropshipperWalletTransaction.unlock_at.is_not(None),
            )
            .order_by(DropshipperWalletTransaction.created_at.asc())
        )
    ).all()

    unlocked_total = 0
    for tx in pending_rows:
        if tx.unlock_at is None or _utc_aware(tx.unlock_at) > current_time:
            continue

        if settings.require_cod_reconciled and tx.order_id is not None:
            shipment = (
                await db.execute(
                    select(CourierShipment).where(CourierShipment.order_id == tx.order_id)
                )
            ).scalar_one_or_none()
            if shipment is None or shipment.settled_at is None:
                continue

        unlock_tx = DropshipperWalletTransaction(
            dropshipper_id=dropshipper_id,
            order_id=tx.order_id,
            entry_type=WalletEntryType.UNLOCK_AVAILABLE.value,
            amount=tx.amount,
            balance_bucket=WalletBucket.AVAILABLE.value,
            idempotency_key=f"unlock:{tx.id}",
            note="Matured pending profit unlocked to available balance",
        )
        if await _insert_ledger_tx(db, unlock_tx):
            tx.unlocked_at = current_time
            profile.pending_balance -= tx.amount
            profile.available_balance += tx.amount
            unlocked_total += tx.amount

    if unlocked_total != 0:
        await db.flush()
    return unlocked_total


# ---------------------------------------------------------------------------
# Dropshipper Wallet, Payouts & Top-Up Endpoints Logic
# ---------------------------------------------------------------------------


async def get_wallet_summary(
    db: AsyncSession, user: User, *, now: datetime | None = None
) -> DropshipperWalletSummary:
    unlocked = await settle_matured_pending_profits(db, user.id, now=now)
    if unlocked != 0:
        await db.commit()

    profile = await _lock_profile_by_user(db, user.id)
    if profile is None:
        raise NotFoundError("Dropshipper profile not found")

    settings = await _get_settings(db)
    active_orders = await count_active_dropship_orders(db, user.id)
    total_completed = profile.delivered_count + profile.returned_count
    rto_rate = (
        round((profile.returned_count / total_completed) * 100, 2) if total_completed else 0.0
    )

    return DropshipperWalletSummary(
        pending_balance=profile.pending_balance,
        available_balance=profile.available_balance,
        locked_withdrawal_balance=profile.locked_withdrawal_balance,
        total_earned=profile.total_earned,
        total_withdrawn=profile.total_withdrawn,
        delivered_count=profile.delivered_count,
        returned_count=profile.returned_count,
        rto_rate=rto_rate,
        tier=DropshipperTier(profile.tier),
        status=DropshipperStatus(profile.status),
        active_orders_count=active_orders,
        new_seller_max_active_orders=settings.new_seller_max_active_orders,
        trusted_delivery_threshold=settings.trusted_delivery_threshold,
        negative_wallet_limit=settings.negative_wallet_limit,
        min_withdrawal_amount=settings.min_withdrawal_amount,
        payout_unlock_days=settings.payout_unlock_days,
        is_blocked_negative_wallet=profile.available_balance < settings.negative_wallet_limit,
        unlocked_just_now=unlocked,
    )


async def list_wallet_transactions(
    db: AsyncSession,
    user: User,
    *,
    entry_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> DropshipperWalletTransactionListResponse:
    unlocked = await settle_matured_pending_profits(db, user.id)
    if unlocked != 0:
        await db.commit()

    conds: list[Any] = [DropshipperWalletTransaction.dropshipper_id == user.id]
    if entry_type:
        conds.append(DropshipperWalletTransaction.entry_type == entry_type)

    total = int(
        await db.scalar(select(func.count(DropshipperWalletTransaction.id)).where(*conds)) or 0
    )
    rows = (
        await db.scalars(
            select(DropshipperWalletTransaction)
            .where(*conds)
            .order_by(DropshipperWalletTransaction.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    return DropshipperWalletTransactionListResponse(
        items=[_tx_to_read(tx) for tx in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def create_payout_request(
    db: AsyncSession,
    user: User,
    payload: DropshipperPayoutCreateRequest,
) -> DropshipperPayoutRead:
    await settle_matured_pending_profits(db, user.id)

    settings = await _get_settings(db)
    if not settings.enabled:
        raise PermissionDeniedError("Dropshipping program is currently disabled")

    profile = await _lock_profile_by_user(db, user.id)
    if profile is None or profile.status != DropshipperStatus.APPROVED.value:
        raise PermissionDeniedError("Only approved dropshippers can request payouts")

    if payload.amount < settings.min_withdrawal_amount:
        raise UnprocessableError(
            f"Minimum withdrawal amount is ৳{settings.min_withdrawal_amount}"
        )
    if profile.available_balance < payload.amount:
        raise UnprocessableError(
            f"Insufficient available balance (৳{profile.available_balance} available)"
        )

    method = payload.payout_method.value if payload.payout_method else profile.payout_method
    account_number = (
        payload.payout_account_number.strip()
        if payload.payout_account_number
        else profile.payout_account_number
    )
    if not account_number:
        raise UnprocessableError("Payout account number is required")

    account_name = (
        payload.payout_account_name.strip()
        if payload.payout_account_name is not None
        else profile.payout_account_name
    )
    bank_name = payload.bank_name if payload.bank_name is not None else profile.bank_name
    bank_branch = payload.bank_branch if payload.bank_branch is not None else profile.bank_branch

    payout = DropshipperPayoutRequest(
        dropshipper_id=user.id,
        amount=payload.amount,
        status=PayoutRequestStatus.PENDING.value,
        payout_method=method,
        payout_account_number=account_number,
        payout_account_name=account_name,
        bank_name=bank_name,
        bank_branch=bank_branch,
    )
    db.add(payout)
    await db.flush()

    lock_tx = DropshipperWalletTransaction(
        dropshipper_id=user.id,
        payout_id=payout.id,
        entry_type=WalletEntryType.DEBIT_WITHDRAWAL_LOCK.value,
        amount=-payload.amount,
        balance_bucket=WalletBucket.LOCKED.value,
        idempotency_key=f"payout:{payout.id}:lock",
        note=f"Withdrawal request locked (৳{payload.amount} via {method})",
    )
    await _insert_ledger_tx(db, lock_tx)

    profile.available_balance -= payload.amount
    profile.locked_withdrawal_balance += payload.amount

    await db.commit()
    await db.refresh(payout)
    return _payout_to_read(payout)


async def list_my_payouts(
    db: AsyncSession,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
) -> DropshipperPayoutListResponse:
    unlocked = await settle_matured_pending_profits(db, user.id)
    if unlocked != 0:
        await db.commit()

    cond = DropshipperPayoutRequest.dropshipper_id == user.id
    total = int(await db.scalar(select(func.count(DropshipperPayoutRequest.id)).where(cond)) or 0)
    rows = (
        await db.scalars(
            select(DropshipperPayoutRequest)
            .where(cond)
            .order_by(DropshipperPayoutRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return DropshipperPayoutListResponse(
        items=[_payout_to_read(p) for p in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def create_topup_request(
    db: AsyncSession,
    user: User,
    payload: DropshipperTopupCreateRequest,
) -> DropshipperTopupRead:
    profile = await _lock_profile_by_user(db, user.id)
    if profile is None or profile.status != DropshipperStatus.APPROVED.value:
        raise PermissionDeniedError("Only approved dropshippers can submit wallet top-ups")

    topup = DropshipperTopupRequest(
        dropshipper_id=user.id,
        amount=payload.amount,
        payment_method=payload.payment_method,
        sender_number=payload.sender_number,
        transaction_id=payload.transaction_id,
        status=TopupRequestStatus.PENDING.value,
    )
    db.add(topup)
    await db.commit()
    await db.refresh(topup)
    return _topup_to_read(topup)


async def list_my_topups(
    db: AsyncSession,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
) -> DropshipperTopupListResponse:
    cond = DropshipperTopupRequest.dropshipper_id == user.id
    total = int(await db.scalar(select(func.count(DropshipperTopupRequest.id)).where(cond)) or 0)
    rows = (
        await db.scalars(
            select(DropshipperTopupRequest)
            .where(cond)
            .order_by(DropshipperTopupRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return DropshipperTopupListResponse(
        items=[_topup_to_read(t) for t in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


# ---------------------------------------------------------------------------
# Admin Payout, Top-Up & Superadmin Wallet Adjustment
# ---------------------------------------------------------------------------


async def admin_list_payouts(
    db: AsyncSession,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AdminDropshipperPayoutListResponse:
    conds: list[Any] = []
    if status:
        conds.append(DropshipperPayoutRequest.status == status)

    total = int(
        await db.scalar(select(func.count(DropshipperPayoutRequest.id)).where(*conds)) or 0
    )
    rows = (
        await db.execute(
            select(DropshipperPayoutRequest, DropshipperProfile, User)
            .join(
                DropshipperProfile,
                DropshipperProfile.user_id == DropshipperPayoutRequest.dropshipper_id,
            )
            .join(User, User.id == DropshipperPayoutRequest.dropshipper_id)
            .where(*conds)
            .order_by(DropshipperPayoutRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminDropshipperPayoutRead(
            **_payout_to_read(payout).model_dump(),
            shop_name=profile.shop_name,
            shop_phone=profile.shop_phone,
            user_full_name=user.full_name,
        )
        for payout, profile, user in rows
    ]
    return AdminDropshipperPayoutListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def admin_mark_payout_paid(
    db: AsyncSession,
    payout_id: uuid.UUID,
    payload: AdminPayoutMarkPaidRequest,
    actor: User,
) -> DropshipperPayoutRead:
    stmt = select(DropshipperPayoutRequest).where(DropshipperPayoutRequest.id == payout_id)
    if not _is_sqlite(db):
        stmt = stmt.with_for_update()
    payout = (await db.execute(stmt)).scalar_one_or_none()
    if payout is None:
        raise NotFoundError("Payout request not found")
    if payout.status != PayoutRequestStatus.PENDING.value:
        raise ConflictError(f"Payout request is already {payout.status}")

    profile = await _lock_profile_by_user(db, payout.dropshipper_id)
    if profile is None:
        raise NotFoundError("Dropshipper profile not found")

    paid_tx = DropshipperWalletTransaction(
        dropshipper_id=payout.dropshipper_id,
        payout_id=payout.id,
        entry_type=WalletEntryType.WITHDRAWAL_PAID.value,
        amount=-payout.amount,
        balance_bucket=WalletBucket.LOCKED.value,
        idempotency_key=f"payout:{payout.id}:paid",
        note=f"Payout paid via {payout.payout_method} (TrxID: {payload.transaction_id})",
        created_by=actor.id,
    )
    inserted = await _insert_ledger_tx(db, paid_tx)
    if not inserted:
        raise ConflictError("Payout was already processed")

    profile.locked_withdrawal_balance = max(0, profile.locked_withdrawal_balance - payout.amount)
    profile.total_withdrawn += payout.amount

    payout.status = PayoutRequestStatus.PAID.value
    payout.transaction_id = payload.transaction_id.strip()
    payout.admin_note = payload.admin_note.strip()
    payout.processed_by = actor.id
    payout.processed_at = datetime.now(UTC)

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_PAYOUT_PAID,
        target_type="dropshipper_payout",
        target_id=payout.id,
        metadata={
            "dropshipper_id": str(payout.dropshipper_id),
            "amount": payout.amount,
            "transaction_id": payout.transaction_id,
        },
    )
    await notification_service.create_dropshipper_notification(
        db,
        payout.dropshipper_id,
        title=f"Payout Paid: ৳{payout.amount}",
        message=(
            f"Your withdrawal of ৳{payout.amount} has been sent to "
            f"{payout.payout_account_number} (TrxID: {payout.transaction_id})."
        ),
        notif_type="dropshipper_payout",
        url="/dropshipper/wallet",
        commit=False,
    )
    await db.commit()
    await db.refresh(payout)
    return _payout_to_read(payout)


async def admin_reject_payout(
    db: AsyncSession,
    payout_id: uuid.UUID,
    payload: AdminPayoutRejectRequest,
    actor: User,
) -> DropshipperPayoutRead:
    stmt = select(DropshipperPayoutRequest).where(DropshipperPayoutRequest.id == payout_id)
    if not _is_sqlite(db):
        stmt = stmt.with_for_update()
    payout = (await db.execute(stmt)).scalar_one_or_none()
    if payout is None:
        raise NotFoundError("Payout request not found")
    if payout.status != PayoutRequestStatus.PENDING.value:
        raise ConflictError(f"Payout request is already {payout.status}")

    profile = await _lock_profile_by_user(db, payout.dropshipper_id)
    if profile is None:
        raise NotFoundError("Dropshipper profile not found")

    refund_tx = DropshipperWalletTransaction(
        dropshipper_id=payout.dropshipper_id,
        payout_id=payout.id,
        entry_type=WalletEntryType.WITHDRAWAL_REFUND.value,
        amount=payout.amount,
        balance_bucket=WalletBucket.AVAILABLE.value,
        idempotency_key=f"payout:{payout.id}:refund",
        note=f"Withdrawal rejected & refunded: {payload.reason.strip()}",
        created_by=actor.id,
    )
    inserted = await _insert_ledger_tx(db, refund_tx)
    if not inserted:
        raise ConflictError("Payout was already processed")

    profile.locked_withdrawal_balance = max(0, profile.locked_withdrawal_balance - payout.amount)
    profile.available_balance += payout.amount

    payout.status = PayoutRequestStatus.REJECTED.value
    payout.admin_note = payload.reason.strip()
    payout.processed_by = actor.id
    payout.processed_at = datetime.now(UTC)

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_PAYOUT_REJECTED,
        target_type="dropshipper_payout",
        target_id=payout.id,
        metadata={
            "dropshipper_id": str(payout.dropshipper_id),
            "amount": payout.amount,
            "reason": payout.admin_note,
        },
    )
    await notification_service.create_dropshipper_notification(
        db,
        payout.dropshipper_id,
        title=f"Payout Rejected: ৳{payout.amount}",
        message=(
            f"Your withdrawal of ৳{payout.amount} was rejected ({payout.admin_note}) "
            f"and refunded to your available balance."
        ),
        notif_type="dropshipper_payout",
        url="/dropshipper/wallet",
        commit=False,
    )
    await db.commit()
    await db.refresh(payout)
    return _payout_to_read(payout)


async def admin_list_topups(
    db: AsyncSession,
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AdminDropshipperTopupListResponse:
    conds: list[Any] = []
    if status:
        conds.append(DropshipperTopupRequest.status == status)

    total = int(
        await db.scalar(select(func.count(DropshipperTopupRequest.id)).where(*conds)) or 0
    )
    rows = (
        await db.execute(
            select(DropshipperTopupRequest, DropshipperProfile, User)
            .join(
                DropshipperProfile,
                DropshipperProfile.user_id == DropshipperTopupRequest.dropshipper_id,
            )
            .join(User, User.id == DropshipperTopupRequest.dropshipper_id)
            .where(*conds)
            .order_by(DropshipperTopupRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminDropshipperTopupRead(
            **_topup_to_read(topup).model_dump(),
            shop_name=profile.shop_name,
            shop_phone=profile.shop_phone,
            user_full_name=user.full_name,
        )
        for topup, profile, user in rows
    ]
    return AdminDropshipperTopupListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def admin_approve_topup(
    db: AsyncSession,
    topup_id: uuid.UUID,
    payload: AdminTopupApproveRequest,
    actor: User,
) -> DropshipperTopupRead:
    stmt = select(DropshipperTopupRequest).where(DropshipperTopupRequest.id == topup_id)
    if not _is_sqlite(db):
        stmt = stmt.with_for_update()
    topup = (await db.execute(stmt)).scalar_one_or_none()
    if topup is None:
        raise NotFoundError("Top-up request not found")
    if topup.status != TopupRequestStatus.PENDING.value:
        raise ConflictError(f"Top-up request is already {topup.status}")

    profile = await _lock_profile_by_user(db, topup.dropshipper_id)
    if profile is None:
        raise NotFoundError("Dropshipper profile not found")

    credit_tx = DropshipperWalletTransaction(
        dropshipper_id=topup.dropshipper_id,
        topup_id=topup.id,
        entry_type=WalletEntryType.CREDIT_TOPUP.value,
        amount=topup.amount,
        balance_bucket=WalletBucket.AVAILABLE.value,
        idempotency_key=f"topup:{topup.id}:approve",
        note=f"Wallet top-up approved (TrxID: {topup.transaction_id})",
        created_by=actor.id,
    )
    inserted = await _insert_ledger_tx(db, credit_tx)
    if not inserted:
        raise ConflictError("Top-up was already processed")

    profile.available_balance += topup.amount
    topup.status = TopupRequestStatus.APPROVED.value
    topup.admin_note = payload.admin_note.strip()
    topup.processed_by = actor.id
    topup.processed_at = datetime.now(UTC)

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_TOPUP_APPROVED,
        target_type="dropshipper_topup",
        target_id=topup.id,
        metadata={
            "dropshipper_id": str(topup.dropshipper_id),
            "amount": topup.amount,
            "transaction_id": topup.transaction_id,
        },
    )
    await notification_service.create_dropshipper_notification(
        db,
        topup.dropshipper_id,
        title=f"Wallet Top-Up Approved: ৳{topup.amount}",
        message=(
            f"Your top-up of ৳{topup.amount} (TrxID: {topup.transaction_id}) has been "
            f"approved. Available balance: ৳{profile.available_balance}."
        ),
        notif_type="dropshipper_topup",
        url="/dropshipper/wallet",
        commit=False,
    )
    await db.commit()
    await db.refresh(topup)
    return _topup_to_read(topup)


async def admin_reject_topup(
    db: AsyncSession,
    topup_id: uuid.UUID,
    payload: AdminTopupRejectRequest,
    actor: User,
) -> DropshipperTopupRead:
    stmt = select(DropshipperTopupRequest).where(DropshipperTopupRequest.id == topup_id)
    if not _is_sqlite(db):
        stmt = stmt.with_for_update()
    topup = (await db.execute(stmt)).scalar_one_or_none()
    if topup is None:
        raise NotFoundError("Top-up request not found")
    if topup.status != TopupRequestStatus.PENDING.value:
        raise ConflictError(f"Top-up request is already {topup.status}")

    topup.status = TopupRequestStatus.REJECTED.value
    topup.admin_note = payload.reason.strip()
    topup.processed_by = actor.id
    topup.processed_at = datetime.now(UTC)

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_TOPUP_REJECTED,
        target_type="dropshipper_topup",
        target_id=topup.id,
        metadata={
            "dropshipper_id": str(topup.dropshipper_id),
            "amount": topup.amount,
            "reason": topup.admin_note,
        },
    )
    await notification_service.create_dropshipper_notification(
        db,
        topup.dropshipper_id,
        title=f"Wallet Top-Up Rejected: ৳{topup.amount}",
        message=f"Your top-up of ৳{topup.amount} was rejected: {topup.admin_note}.",
        notif_type="dropshipper_topup",
        url="/dropshipper/wallet",
        commit=False,
    )
    await db.commit()
    await db.refresh(topup)
    return _topup_to_read(topup)


async def admin_adjust_wallet(
    db: AsyncSession,
    profile_id: uuid.UUID,
    payload: AdminWalletAdjustRequest,
    actor: User,
) -> DropshipperProfileRead:
    profile = await _lock_profile_by_id(db, profile_id)
    if profile is None:
        raise NotFoundError("Dropshipper profile not found")

    adj_tx = DropshipperWalletTransaction(
        dropshipper_id=profile.user_id,
        entry_type=WalletEntryType.ADMIN_ADJUSTMENT.value,
        amount=payload.amount,
        balance_bucket=WalletBucket.AVAILABLE.value,
        idempotency_key=f"admin_adjust:{uuid.uuid4()}",
        note=payload.reason.strip(),
        created_by=actor.id,
    )
    await _insert_ledger_tx(db, adj_tx)
    profile.available_balance += payload.amount

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_WALLET_ADJUSTED,
        target_type="dropshipper_profile",
        target_id=profile.id,
        metadata={
            "dropshipper_id": str(profile.user_id),
            "amount": payload.amount,
            "reason": payload.reason.strip(),
            "new_available_balance": profile.available_balance,
        },
    )
    sign = "+" if payload.amount > 0 else ""
    await notification_service.create_dropshipper_notification(
        db,
        profile.user_id,
        title=f"Wallet Adjusted: {sign}৳{payload.amount}",
        message=(
            f"Admin adjusted your wallet by {sign}৳{payload.amount} ({payload.reason.strip()})."
        ),
        notif_type="dropshipper_wallet",
        url="/dropshipper/wallet",
        commit=False,
    )
    await db.commit()
    await db.refresh(profile)
    return dropshipping_service._profile_read(profile)
