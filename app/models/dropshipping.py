"""Dropshipping partner profiles, settings, wallet ledger, payouts, and topups."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import User


class DropshipperStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class DropshipperTier(StrEnum):
    NEW = "new"
    TRUSTED = "trusted"
    PRO = "pro"


class PayoutMethod(StrEnum):
    BKASH = "bkash"
    NAGAD = "nagad"
    ROCKET = "rocket"
    BANK = "bank"


class RtoChargeMode(StrEnum):
    ORDER_SHIPPING = "order_shipping"
    FIXED = "fixed"


class WalletEntryType(StrEnum):
    CREDIT_PENDING = "credit_pending"
    UNLOCK_AVAILABLE = "unlock_available"
    DEBIT_RTO = "debit_rto"
    DEBIT_WITHDRAWAL_LOCK = "debit_withdrawal_lock"
    WITHDRAWAL_PAID = "withdrawal_paid"
    WITHDRAWAL_REFUND = "withdrawal_refund"
    CREDIT_TOPUP = "credit_topup"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class WalletBucket(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    LOCKED = "locked"


class PayoutRequestStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    REJECTED = "rejected"


class TopupRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DropshippingSettings(TimestampMixin, Base):
    """Singleton platform-wide dropshipping policy (id = 1)."""

    __tablename__ = "dropshipping_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("registration_fee >= 0", name="registration_fee_non_negative"),
        CheckConstraint(
            "new_seller_max_active_orders >= 0",
            name="new_seller_max_active_orders_non_negative",
        ),
        CheckConstraint(
            "trusted_delivery_threshold >= 0",
            name="trusted_delivery_threshold_non_negative",
        ),
        CheckConstraint("negative_wallet_limit <= 0", name="negative_wallet_limit_non_positive"),
        CheckConstraint("payout_unlock_days >= 0", name="payout_unlock_days_non_negative"),
        CheckConstraint("min_withdrawal_amount >= 0", name="min_withdrawal_amount_non_negative"),
        CheckConstraint(
            "rto_charge_mode IN ('order_shipping', 'fixed')",
            name="rto_charge_mode_known",
        ),
        CheckConstraint("rto_fixed_fee >= 0", name="rto_fixed_fee_non_negative"),
        CheckConstraint(
            "platform_fee_percent >= 0 AND platform_fee_percent <= 100",
            name="platform_fee_percent_range",
        ),
        CheckConstraint("packaging_fee_flat >= 0", name="packaging_fee_flat_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    registration_fee: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    new_seller_max_active_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    trusted_delivery_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    negative_wallet_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=-200, server_default="-200"
    )
    payout_unlock_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    require_cod_reconciled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    min_withdrawal_amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=500, server_default="500"
    )
    rto_charge_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RtoChargeMode.ORDER_SHIPPING.value,
        server_default=RtoChargeMode.ORDER_SHIPPING.value,
    )
    rto_fixed_fee: Mapped[int] = mapped_column(
        Integer, nullable=False, default=130, server_default="130"
    )
    platform_fee_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    packaging_fee_flat: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class DropshipperProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """KYC, shop branding, payout details, and cached wallet counters for a dropshipper."""

    __tablename__ = "dropshipper_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_dropshipper_profiles_user_id"),
        UniqueConstraint("shop_slug", name="uq_dropshipper_profiles_shop_slug"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'suspended')",
            name="status_known",
        ),
        CheckConstraint(
            "tier IN ('new', 'trusted', 'pro')",
            name="tier_known",
        ),
        CheckConstraint(
            "payout_method IN ('bkash', 'nagad', 'rocket', 'bank')",
            name="payout_method_known",
        ),
        CheckConstraint(
            "locked_withdrawal_balance >= 0 AND total_earned >= 0 AND total_withdrawn >= 0 "
            "AND delivered_count >= 0 AND returned_count >= 0",
            name="counters_non_negative",
        ),
        Index("ix_dropshipper_profiles_status", "status"),
        Index("ix_dropshipper_profiles_shop_slug", "shop_slug"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DropshipperStatus.PENDING.value,
        server_default=DropshipperStatus.PENDING.value,
    )
    tier: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DropshipperTier.NEW.value,
        server_default=DropshipperTier.NEW.value,
    )
    shop_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(160), nullable=False)
    shop_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    shop_logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shop_address: Mapped[str] = mapped_column(
        String(400), nullable=False, default="", server_default=""
    )
    business_url: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    nid_number: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", server_default=""
    )
    nid_front_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    nid_back_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payout_method: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=PayoutMethod.BKASH.value,
        server_default=PayoutMethod.BKASH.value,
    )
    payout_account_number: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    payout_account_name: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default=""
    )
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_branch: Mapped[str | None] = mapped_column(String(120), nullable=True)

    pending_balance: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    available_balance: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_withdrawal_balance: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_earned: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_withdrawn: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    delivered_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    returned_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class DropshipperWalletTransaction(UUIDPrimaryKeyMixin, Base):
    """Immutable double-entry ledger for dropshipper profit credits, RTO debits, and payouts."""

    __tablename__ = "dropshipper_wallet_transactions"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_dropshipper_wallet_transactions_idempotency_key"
        ),
        CheckConstraint(
            "entry_type IN ('credit_pending', 'unlock_available', 'debit_rto', "
            "'debit_withdrawal_lock', 'withdrawal_paid', 'withdrawal_refund', "
            "'credit_topup', 'admin_adjustment')",
            name="entry_type_known",
        ),
        CheckConstraint(
            "balance_bucket IN ('pending', 'available', 'locked')",
            name="balance_bucket_known",
        ),
        Index("ix_dropshipper_wallet_tx_dropshipper_id", "dropshipper_id"),
        Index("ix_dropshipper_wallet_tx_unlock_at", "unlock_at"),
        Index(
            "ix_dropshipper_wallet_tx_dropshipper_created",
            "dropshipper_id",
            text("created_at DESC"),
        ),
    )

    dropshipper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    payout_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    topup_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_bucket: Mapped[str] = mapped_column(String(24), nullable=False)
    unlock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DropshipperPayoutRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Withdrawal request submitted by an approved dropshipper."""

    __tablename__ = "dropshipper_payout_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("status IN ('pending', 'paid', 'rejected')", name="status_known"),
        CheckConstraint(
            "payout_method IN ('bkash', 'nagad', 'rocket', 'bank')",
            name="payout_method_known",
        ),
        Index("ix_dropshipper_payout_requests_dropshipper_id", "dropshipper_id"),
        Index("ix_dropshipper_payout_requests_status", "status"),
    )

    dropshipper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=PayoutRequestStatus.PENDING.value,
        server_default=PayoutRequestStatus.PENDING.value,
    )
    payout_method: Mapped[str] = mapped_column(String(24), nullable=False)
    payout_account_number: Mapped[str] = mapped_column(String(64), nullable=False)
    payout_account_name: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default=""
    )
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_branch: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    admin_note: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    processed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DropshipperTopupRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Wallet top-up request (e.g. to clear negative RTO balance) submitted by a dropshipper."""

    __tablename__ = "dropshipper_topup_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status_known"),
        Index("ix_dropshipper_topup_requests_dropshipper_id", "dropshipper_id"),
        Index("ix_dropshipper_topup_requests_status", "status"),
    )

    dropshipper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)
    sender_number: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=TopupRequestStatus.PENDING.value,
        server_default=TopupRequestStatus.PENDING.value,
    )
    admin_note: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    processed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
