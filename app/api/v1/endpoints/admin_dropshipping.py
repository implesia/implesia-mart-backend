"""Admin dropshipping management endpoints (/api/v1/admin/dropshipping/*)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, RequireSuperadmin, no_store, require_module_access
from app.models.user import User
from app.schemas.dropshipping import (
    AdminDropshipperListResponse,
    AdminDropshipperPartnerRead,
    AdminDropshipperPayoutListResponse,
    AdminDropshipperTopupListResponse,
    AdminDropshippingOverview,
    AdminPayoutMarkPaidRequest,
    AdminPayoutRejectRequest,
    AdminRejectPartnerRequest,
    AdminSuspendPartnerRequest,
    AdminTopupApproveRequest,
    AdminTopupRejectRequest,
    AdminWalletAdjustRequest,
    DropshipperPayoutRead,
    DropshipperProfileRead,
    DropshipperTopupRead,
    DropshippingSettingsRead,
    DropshippingSettingsUpdate,
)
from app.services import dropship_wallet_service, dropshipping_service

router = APIRouter(dependencies=[Depends(no_store)])

RequireDropshippingRead = Annotated[User, Depends(require_module_access("dropshipping", "read"))]
RequireDropshippingWrite = Annotated[User, Depends(require_module_access("dropshipping", "write"))]


@router.get("/overview", response_model=AdminDropshippingOverview)
async def get_dropshipping_overview(
    db: DbSession,
    _actor: RequireDropshippingRead,
) -> AdminDropshippingOverview:
    return await dropshipping_service.admin_overview(db)


@router.get("/settings", response_model=DropshippingSettingsRead)
async def get_dropshipping_settings(
    db: DbSession,
    _actor: RequireDropshippingRead,
) -> DropshippingSettingsRead:
    return await dropshipping_service.get_settings(db)


@router.patch("/settings", response_model=DropshippingSettingsRead)
async def patch_dropshipping_settings(
    payload: DropshippingSettingsUpdate,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> DropshippingSettingsRead:
    return await dropshipping_service.update_settings(db, payload, actor)


@router.get("/partners", response_model=AdminDropshipperListResponse)
async def list_dropshipping_partners(
    db: DbSession,
    _actor: RequireDropshippingRead,
    status: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminDropshipperListResponse:
    return await dropshipping_service.admin_list_partners(
        db, status=status, tier=tier, q=q, page=page, page_size=page_size
    )


@router.get("/partners/{profile_id}", response_model=AdminDropshipperPartnerRead)
async def get_dropshipping_partner(
    profile_id: uuid.UUID,
    db: DbSession,
    _actor: RequireDropshippingRead,
) -> AdminDropshipperPartnerRead:
    return await dropshipping_service.admin_get_partner(db, profile_id)


@router.post("/partners/{profile_id}/approve", response_model=AdminDropshipperPartnerRead)
async def approve_dropshipping_partner(
    profile_id: uuid.UUID,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> AdminDropshipperPartnerRead:
    return await dropshipping_service.admin_approve_partner(db, profile_id, actor)


@router.post("/partners/{profile_id}/reject", response_model=AdminDropshipperPartnerRead)
async def reject_dropshipping_partner(
    profile_id: uuid.UUID,
    payload: AdminRejectPartnerRequest,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> AdminDropshipperPartnerRead:
    return await dropshipping_service.admin_reject_partner(db, profile_id, payload.reason, actor)


@router.post("/partners/{profile_id}/suspend", response_model=AdminDropshipperPartnerRead)
async def suspend_dropshipping_partner(
    profile_id: uuid.UUID,
    payload: AdminSuspendPartnerRequest,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> AdminDropshipperPartnerRead:
    return await dropshipping_service.admin_suspend_partner(db, profile_id, payload.reason, actor)


@router.post("/partners/{profile_id}/reactivate", response_model=AdminDropshipperPartnerRead)
async def reactivate_dropshipping_partner(
    profile_id: uuid.UUID,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> AdminDropshipperPartnerRead:
    return await dropshipping_service.admin_reactivate_partner(db, profile_id, actor)


# ---------------------------------------------------------------------------
# Phase 32: Payouts, Top-Ups & Superadmin Wallet Adjustments
# ---------------------------------------------------------------------------


@router.get("/payouts", response_model=AdminDropshipperPayoutListResponse)
async def admin_list_dropshipping_payouts(
    db: DbSession,
    _actor: RequireDropshippingRead,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminDropshipperPayoutListResponse:
    return await dropship_wallet_service.admin_list_payouts(
        db, status=status, page=page, page_size=page_size
    )


@router.post("/payouts/{payout_id}/mark-paid", response_model=DropshipperPayoutRead)
async def admin_mark_dropshipping_payout_paid(
    payout_id: uuid.UUID,
    payload: AdminPayoutMarkPaidRequest,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> DropshipperPayoutRead:
    return await dropship_wallet_service.admin_mark_payout_paid(db, payout_id, payload, actor)


@router.post("/payouts/{payout_id}/reject", response_model=DropshipperPayoutRead)
async def admin_reject_dropshipping_payout(
    payout_id: uuid.UUID,
    payload: AdminPayoutRejectRequest,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> DropshipperPayoutRead:
    return await dropship_wallet_service.admin_reject_payout(db, payout_id, payload, actor)


@router.get("/topups", response_model=AdminDropshipperTopupListResponse)
async def admin_list_dropshipping_topups(
    db: DbSession,
    _actor: RequireDropshippingRead,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminDropshipperTopupListResponse:
    return await dropship_wallet_service.admin_list_topups(
        db, status=status, page=page, page_size=page_size
    )


@router.post("/topups/{topup_id}/approve", response_model=DropshipperTopupRead)
async def admin_approve_dropshipping_topup(
    topup_id: uuid.UUID,
    payload: AdminTopupApproveRequest,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> DropshipperTopupRead:
    return await dropship_wallet_service.admin_approve_topup(db, topup_id, payload, actor)


@router.post("/topups/{topup_id}/reject", response_model=DropshipperTopupRead)
async def admin_reject_dropshipping_topup(
    topup_id: uuid.UUID,
    payload: AdminTopupRejectRequest,
    db: DbSession,
    actor: RequireDropshippingWrite,
) -> DropshipperTopupRead:
    return await dropship_wallet_service.admin_reject_topup(db, topup_id, payload, actor)


@router.post("/wallets/{profile_id}/adjust", response_model=DropshipperProfileRead)
async def admin_adjust_dropshipper_wallet(
    profile_id: uuid.UUID,
    payload: AdminWalletAdjustRequest,
    db: DbSession,
    actor: RequireSuperadmin,
) -> DropshipperProfileRead:
    return await dropship_wallet_service.admin_adjust_wallet(db, profile_id, payload, actor)
