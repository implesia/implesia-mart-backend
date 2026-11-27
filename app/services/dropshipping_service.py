"""Dropshipping business logic: settings, KYC onboarding, catalog, and admin partner lifecycle."""

import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.models.audit_event import AuditAction
from app.models.dropshipping import (
    DropshipperProfile,
    DropshipperStatus,
    DropshipperTier,
    DropshippingSettings,
    PayoutMethod,
    RtoChargeMode,
)
from app.models.notification import CustomerNotification
from app.models.product import Product, ProductVariant
from app.models.user import User, UserRole
from app.schemas.dropshipping import (
    AdminDropshipperListResponse,
    AdminDropshipperPartnerRead,
    AdminDropshippingOverview,
    DropshipperApplyRequest,
    DropshipperCatalogMediaItem,
    DropshipperCatalogProduct,
    DropshipperCatalogResponse,
    DropshipperCatalogVariant,
    DropshipperMeResponse,
    DropshipperProfileRead,
    DropshipperProfileUpdate,
    DropshippingSettingsRead,
    DropshippingSettingsSummary,
    DropshippingSettingsUpdate,
)
from app.services import (
    audit_service,
    category_service,
    notification_service,
    permission_service,
    product_service,
    variant_service,
)
from app.services.realtime_hub import realtime_hub, user_channel

_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


def _slugify_shop(raw: str) -> str:
    cleaned = _SLUG_CLEAN.sub("-", raw.strip().lower()).strip("-")
    return (cleaned or "shop")[:72]


async def _unique_shop_slug(
    db: AsyncSession,
    desired: str,
    *,
    exclude_profile_id: uuid.UUID | None = None,
) -> str:
    base = _slugify_shop(desired)
    candidate = base
    suffix = 2
    while True:
        stmt = select(DropshipperProfile.id).where(DropshipperProfile.shop_slug == candidate)
        if exclude_profile_id is not None:
            stmt = stmt.where(DropshipperProfile.id != exclude_profile_id)
        existing = await db.scalar(stmt)
        if existing is None:
            return candidate
        candidate = f"{base[:68]}-{suffix}"
        suffix += 1


def _rto_rate(delivered: int, returned: int) -> float:
    total = delivered + returned
    if total <= 0:
        return 0.0
    return round((returned / total) * 100.0, 2)


def _profile_read(profile: DropshipperProfile) -> DropshipperProfileRead:
    return DropshipperProfileRead(
        id=profile.id,
        user_id=profile.user_id,
        status=DropshipperStatus(profile.status),
        tier=DropshipperTier(profile.tier),
        shop_slug=profile.shop_slug,
        shop_name=profile.shop_name,
        shop_phone=profile.shop_phone,
        shop_logo_url=profile.shop_logo_url,
        shop_address=profile.shop_address,
        business_url=profile.business_url,
        nid_number=profile.nid_number,
        nid_front_url=profile.nid_front_url,
        nid_back_url=profile.nid_back_url,
        payout_method=PayoutMethod(profile.payout_method),
        payout_account_number=profile.payout_account_number,
        payout_account_name=profile.payout_account_name,
        bank_name=profile.bank_name,
        bank_branch=profile.bank_branch,
        pending_balance=profile.pending_balance,
        available_balance=profile.available_balance,
        locked_withdrawal_balance=profile.locked_withdrawal_balance,
        total_earned=profile.total_earned,
        total_withdrawn=profile.total_withdrawn,
        delivered_count=profile.delivered_count,
        returned_count=profile.returned_count,
        rto_rate=_rto_rate(profile.delivered_count, profile.returned_count),
        rejection_reason=profile.rejection_reason,
        approved_at=profile.approved_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _partner_read(profile: DropshipperProfile, user: User) -> AdminDropshipperPartnerRead:
    base = _profile_read(profile)
    return AdminDropshipperPartnerRead(
        **base.model_dump(),
        user_full_name=user.full_name,
        user_email=user.email,
        user_phone=user.phone,
        user_role=user.role,
    )


def _settings_read(row: DropshippingSettings) -> DropshippingSettingsRead:
    return DropshippingSettingsRead(
        enabled=row.enabled,
        registration_fee=row.registration_fee,
        new_seller_max_active_orders=row.new_seller_max_active_orders,
        trusted_delivery_threshold=row.trusted_delivery_threshold,
        negative_wallet_limit=row.negative_wallet_limit,
        payout_unlock_days=row.payout_unlock_days,
        require_cod_reconciled=row.require_cod_reconciled,
        min_withdrawal_amount=row.min_withdrawal_amount,
        rto_charge_mode=RtoChargeMode(row.rto_charge_mode),
        rto_fixed_fee=row.rto_fixed_fee,
        platform_fee_percent=row.platform_fee_percent,
        packaging_fee_flat=row.packaging_fee_flat,
        updated_at=row.updated_at,
    )


def _settings_summary(row: DropshippingSettings) -> DropshippingSettingsSummary:
    return DropshippingSettingsSummary(
        enabled=row.enabled,
        registration_fee=row.registration_fee,
        new_seller_max_active_orders=row.new_seller_max_active_orders,
        trusted_delivery_threshold=row.trusted_delivery_threshold,
        payout_unlock_days=row.payout_unlock_days,
        min_withdrawal_amount=row.min_withdrawal_amount,
        rto_charge_mode=RtoChargeMode(row.rto_charge_mode),
        rto_fixed_fee=row.rto_fixed_fee,
        platform_fee_percent=row.platform_fee_percent,
        packaging_fee_flat=row.packaging_fee_flat,
    )


async def get_settings_row(db: AsyncSession) -> DropshippingSettings:
    row = await db.get(DropshippingSettings, 1)
    if row is None:
        row = DropshippingSettings(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def get_settings(db: AsyncSession) -> DropshippingSettingsRead:
    return _settings_read(await get_settings_row(db))


async def update_settings(
    db: AsyncSession,
    payload: DropshippingSettingsUpdate,
    actor: User,
) -> DropshippingSettingsRead:
    row = await get_settings_row(db)
    changes: dict[str, object] = {}
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        stored_val = value.value if isinstance(value, RtoChargeMode) else value
        if getattr(row, field_name) != stored_val:
            setattr(row, field_name, stored_val)
            changes[field_name] = stored_val
    if changes:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.DROPSHIPPING_SETTINGS_UPDATED,
            target_type="dropshipping_settings",
            target_id="1",
            metadata=changes,
        )
        await db.commit()
        await db.refresh(row)
    return _settings_read(row)


async def get_me(db: AsyncSession, user: User) -> DropshipperMeResponse:
    settings_row = await get_settings_row(db)
    profile = await db.scalar(
        select(DropshipperProfile).where(DropshipperProfile.user_id == user.id)
    )
    return DropshipperMeResponse(
        profile=_profile_read(profile) if profile is not None else None,
        settings=_settings_summary(settings_row),
    )


async def apply_dropshipper(
    db: AsyncSession,
    user: User,
    payload: DropshipperApplyRequest,
) -> DropshipperProfileRead:
    settings_row = await get_settings_row(db)
    if not settings_row.enabled:
        raise UnprocessableError("Dropshipping applications are currently paused")

    existing = await db.scalar(
        select(DropshipperProfile).where(DropshipperProfile.user_id == user.id)
    )
    if existing is not None:
        if existing.status == DropshipperStatus.APPROVED.value:
            raise ConflictError("You are already an approved dropshipping partner")
        if existing.status == DropshipperStatus.PENDING.value:
            raise ConflictError("Your dropshipping application is already pending review")
        if existing.status == DropshipperStatus.SUSPENDED.value:
            raise PermissionDeniedError("Suspended dropshipper accounts cannot re-apply")
        # Rejected -> allow clean re-application
        slug = await _unique_shop_slug(
            db,
            payload.shop_slug or payload.shop_name,
            exclude_profile_id=existing.id,
        )
        existing.status = DropshipperStatus.PENDING.value
        existing.rejection_reason = None
        existing.shop_slug = slug
        existing.shop_name = payload.shop_name
        existing.shop_phone = payload.shop_phone
        existing.shop_logo_url = payload.shop_logo_url
        existing.shop_address = payload.shop_address
        existing.business_url = payload.business_url
        existing.nid_number = payload.nid_number
        existing.nid_front_url = payload.nid_front_url
        existing.nid_back_url = payload.nid_back_url
        existing.payout_method = payload.payout_method.value
        existing.payout_account_number = payload.payout_account_number
        existing.payout_account_name = payload.payout_account_name
        existing.bank_name = payload.bank_name
        existing.bank_branch = payload.bank_branch
        await db.commit()
        await db.refresh(existing)
        return _profile_read(existing)

    slug = await _unique_shop_slug(db, payload.shop_slug or payload.shop_name)
    profile = DropshipperProfile(
        user_id=user.id,
        status=DropshipperStatus.PENDING.value,
        tier=DropshipperTier.NEW.value,
        shop_slug=slug,
        shop_name=payload.shop_name,
        shop_phone=payload.shop_phone,
        shop_logo_url=payload.shop_logo_url,
        shop_address=payload.shop_address,
        business_url=payload.business_url,
        nid_number=payload.nid_number,
        nid_front_url=payload.nid_front_url,
        nid_back_url=payload.nid_back_url,
        payout_method=payload.payout_method.value,
        payout_account_number=payload.payout_account_number,
        payout_account_name=payload.payout_account_name,
        bank_name=payload.bank_name,
        bank_branch=payload.bank_branch,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return _profile_read(profile)


async def update_profile(
    db: AsyncSession,
    user: User,
    payload: DropshipperProfileUpdate,
) -> DropshipperProfileRead:
    profile = await db.scalar(
        select(DropshipperProfile).where(DropshipperProfile.user_id == user.id)
    )
    if profile is None:
        raise NotFoundError("Dropshipper profile not found")
    if profile.status == DropshipperStatus.SUSPENDED.value:
        raise PermissionDeniedError("Suspended accounts cannot edit their profile")

    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "payout_method" and value is not None:
            setattr(profile, key, value.value if isinstance(value, PayoutMethod) else str(value))
        else:
            setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return _profile_read(profile)


def _extract_catalog_media(product: Product) -> list[DropshipperCatalogMediaItem]:
    items: list[DropshipperCatalogMediaItem] = []
    seen_urls: set[str] = set()
    if product.image_src:
        items.append(
            DropshipperCatalogMediaItem(
                kind="image",
                url=product.image_src,
                alt=product.image_alt or product.title,
            )
        )
        seen_urls.add(product.image_src)
    raw_gallery = (product.content or {}).get("gallery")
    if isinstance(raw_gallery, list):
        for entry in raw_gallery:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind") or "image"
            if kind not in {"image", "video", "youtube"}:
                kind = "image"
            src = str(entry.get("src") or "").strip()
            yt_id = str(entry.get("youtube_id") or "").strip()
            thumb = str(entry.get("thumbnail") or "").strip()
            alt = str(entry.get("alt") or "")
            if kind == "youtube" and yt_id:
                url = f"https://www.youtube.com/watch?v={yt_id}"
                if url not in seen_urls:
                    seen_urls.add(url)
                    items.append(
                        DropshipperCatalogMediaItem(
                            kind="youtube",
                            url=url,
                            youtube_id=yt_id,
                            thumbnail=thumb,
                            alt=alt,
                        )
                    )
            elif src and src not in seen_urls:
                seen_urls.add(src)
                items.append(
                    DropshipperCatalogMediaItem(
                        kind=kind,
                        url=src,
                        thumbnail=thumb,
                        alt=alt,
                    )
                )
    return items


async def list_catalog(
    db: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 24,
) -> DropshipperCatalogResponse:
    page = max(1, page)
    page_size = max(1, min(page_size, 60))

    index = await category_service.load_index(db)
    conditions: list[Any] = [
        Product.published.is_(True),
        Product.allow_dropshipping.is_(True),
        Product.dropship_price.is_not(None),
    ]
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(Product.title).like(needle),
                func.lower(Product.slug).like(needle),
                func.lower(Product.subtitle).like(needle),
            )
        )
    if category and category.strip():
        cat_token = category.strip().lower()
        matching_ids: set[uuid.UUID] = set()
        for node in index.by_id.values():
            if node.slug.lower() == cat_token or str(node.id) == cat_token:
                matching_ids.update(index.descendants(node.id))
        if matching_ids:
            conditions.append(Product.category_id.in_(matching_ids))
        else:
            return DropshipperCatalogResponse(
                items=[], total=0, page=page, page_size=page_size, pages=1
            )

    total = int(
        await db.scalar(select(func.count()).select_from(Product).where(*conditions)) or 0
    )
    pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
    offset = (page - 1) * page_size

    products = list(
        (
            await db.scalars(
                select(Product)
                .where(*conditions)
                .order_by(Product.sort_order.asc(), Product.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).all()
    )

    product_ids = [p.id for p in products]
    variants_by_product: dict[uuid.UUID, list[ProductVariant]] = {}
    if product_ids:
        v_rows = (
            await db.scalars(
                select(ProductVariant)
                .where(
                    ProductVariant.product_id.in_(product_ids),
                    ProductVariant.is_active.is_(True),
                )
                .order_by(ProductVariant.sort_order.asc())
            )
        ).all()
        for row in v_rows:
            variants_by_product.setdefault(row.product_id, []).append(row)

    result_items: list[DropshipperCatalogProduct] = []
    for p in products:
        assert p.dropship_price is not None
        cat_node = index.by_id.get(p.category_id) if p.category_id else None
        content = product_service.content_of(p)
        v_items = [
            DropshipperCatalogVariant(
                id=v.id,
                options=dict(v.options),
                label=variant_service.label_of(content, v.options),
                sku=v.sku,
                dropship_price=(
                    v.dropship_price if v.dropship_price is not None else p.dropship_price
                ),
                suggested_retail_price=v.price,
                stock_quantity=v.quantity,
                weight_grams=v.weight_grams if v.weight_grams is not None else p.weight_grams,
                is_active=v.is_active,
            )
            for v in variants_by_product.get(p.id, [])
        ]
        result_items.append(
            DropshipperCatalogProduct(
                id=p.id,
                slug=p.slug,
                title=p.title,
                subtitle=p.subtitle,
                category_id=p.category_id,
                category_slug=cat_node.slug if cat_node else (p.category or ""),
                category_name=cat_node.name if cat_node else "",
                dropship_price=p.dropship_price,
                suggested_retail_price=p.price,
                min_sell_price=p.min_sell_price,
                max_sell_price=p.max_sell_price,
                stock_quantity=p.quantity,
                weight_grams=p.weight_grams,
                status=p.status,
                has_variants=p.has_variants,
                image_src=p.image_src,
                media=_extract_catalog_media(p),
                variants=v_items,
            )
        )

    return DropshipperCatalogResponse(
        items=result_items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def _notify_partner_status(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    title: str,
    message: str,
    notif_type: str = "dropshipper_status",
) -> None:
    notification = CustomerNotification(
        user_id=user_id,
        order_id=None,
        type=notif_type,
        title=title[:160],
        message=message[:1000],
        language="en",
        is_read=False,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    unread_count = await notification_service.count_unread_notifications(db, user_id)
    channel = user_channel(user_id)
    await realtime_hub.publish(
        channel,
        "notification.created",
        {
            "id": str(notification.id),
            "order_id": None,
            "type": notification.type,
            "title": notification.title,
            "message": notification.message,
            "is_read": notification.is_read,
            "language": notification.language,
            "created_at": notification.created_at.isoformat(),
            "unread_count": unread_count,
        },
    )
    await realtime_hub.publish(
        channel,
        "notification.unread",
        {"unread_count": unread_count},
    )
    from app.services import push_service

    if push_service.is_configured():
        push_service.schedule_push_to_users(
            None,
            [user_id],
            "customer",
            push_service.build_push_payload(
                title=notification.title,
                body=notification.message,
                url="/dropshipper",
                tag=f"implesia-dropshipper-{notification.id}",
                scope="customer",
                can_quick_reply=False,
            ),
        )


async def admin_overview(db: AsyncSession) -> AdminDropshippingOverview:
    settings_row = await get_settings_row(db)
    grouped = (
        await db.execute(
            select(DropshipperProfile.status, func.count()).group_by(DropshipperProfile.status)
        )
    ).all()
    counts: dict[str, int] = {str(status): int(cnt) for status, cnt in grouped}
    balances = (
        await db.execute(
            select(
                func.coalesce(func.sum(DropshipperProfile.pending_balance), 0),
                func.coalesce(func.sum(DropshipperProfile.available_balance), 0),
                func.coalesce(func.sum(DropshipperProfile.locked_withdrawal_balance), 0),
            )
        )
    ).one()
    catalog_count = int(
        await db.scalar(
            select(func.count())
            .select_from(Product)
            .where(
                Product.published.is_(True),
                Product.allow_dropshipping.is_(True),
                Product.dropship_price.is_not(None),
            )
        )
        or 0
    )
    return AdminDropshippingOverview(
        enabled=settings_row.enabled,
        total_partners=sum(counts.values()),
        pending_count=counts.get(DropshipperStatus.PENDING.value, 0),
        approved_count=counts.get(DropshipperStatus.APPROVED.value, 0),
        rejected_count=counts.get(DropshipperStatus.REJECTED.value, 0),
        suspended_count=counts.get(DropshipperStatus.SUSPENDED.value, 0),
        catalog_products_count=catalog_count,
        total_pending_balance=int(balances[0] or 0),
        total_available_balance=int(balances[1] or 0),
        total_locked_balance=int(balances[2] or 0),
    )


async def admin_list_partners(
    db: AsyncSession,
    *,
    status: str | None = None,
    tier: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AdminDropshipperListResponse:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    conditions = []
    if status and status != "all":
        conditions.append(DropshipperProfile.status == status)
    if tier and tier != "all":
        conditions.append(DropshipperProfile.tier == tier)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(DropshipperProfile.shop_name).like(needle),
                func.lower(DropshipperProfile.shop_slug).like(needle),
                func.lower(DropshipperProfile.shop_phone).like(needle),
                func.lower(User.full_name).like(needle),
                func.lower(func.coalesce(User.email, "")).like(needle),
                func.lower(func.coalesce(User.phone, "")).like(needle),
            )
        )

    total = int(
        await db.scalar(
            select(func.count())
            .select_from(DropshipperProfile)
            .join(User, User.id == DropshipperProfile.user_id)
            .where(*conditions)
        )
        or 0
    )
    pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
    rows = (
        await db.execute(
            select(DropshipperProfile, User)
            .join(User, User.id == DropshipperProfile.user_id)
            .where(*conditions)
            .order_by(DropshipperProfile.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [_partner_read(profile, user) for profile, user in rows]
    return AdminDropshipperListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def _load_partner_pair(
    db: AsyncSession, profile_id: uuid.UUID
) -> tuple[DropshipperProfile, User]:
    row = (
        await db.execute(
            select(DropshipperProfile, User)
            .join(User, User.id == DropshipperProfile.user_id)
            .where(DropshipperProfile.id == profile_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Dropshipper partner not found")
    return row[0], row[1]


async def admin_get_partner(
    db: AsyncSession, profile_id: uuid.UUID
) -> AdminDropshipperPartnerRead:
    profile, user = await _load_partner_pair(db, profile_id)
    return _partner_read(profile, user)


async def admin_approve_partner(
    db: AsyncSession,
    profile_id: uuid.UUID,
    actor: User,
) -> AdminDropshipperPartnerRead:
    await permission_service.ensure_system_roles(db)
    profile, user = await _load_partner_pair(db, profile_id)

    profile.status = DropshipperStatus.APPROVED.value
    profile.rejection_reason = None
    profile.approved_at = datetime.now(UTC)
    profile.approved_by = actor.id

    # Upgrade role to `dropshipper` ONLY if user is currently `customer` — NEVER downgrade staff!
    role_upgraded = False
    if user.role == UserRole.CUSTOMER.value:
        user.role = UserRole.DROPSHIPPER.value
        role_upgraded = True

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_APPROVED,
        target_type="dropshipper_profile",
        target_id=str(profile.id),
        metadata={
            "user_id": str(user.id),
            "shop_name": profile.shop_name,
            "shop_slug": profile.shop_slug,
            "role_upgraded": role_upgraded,
        },
    )
    await db.commit()
    await db.refresh(profile)
    await db.refresh(user)

    await _notify_partner_status(
        db,
        user.id,
        title="Dropshipper Application Approved",
        message=(
            f"Congratulations! Your shop “{profile.shop_name}” has been approved. "
            "You can now access the wholesale dropshipping catalog."
        ),
    )
    return _partner_read(profile, user)


async def admin_reject_partner(
    db: AsyncSession,
    profile_id: uuid.UUID,
    reason: str,
    actor: User,
) -> AdminDropshipperPartnerRead:
    profile, user = await _load_partner_pair(db, profile_id)
    cleaned = reason.strip()
    profile.status = DropshipperStatus.REJECTED.value
    profile.rejection_reason = cleaned

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_REJECTED,
        target_type="dropshipper_profile",
        target_id=str(profile.id),
        metadata={"user_id": str(user.id), "reason": cleaned},
    )
    await db.commit()
    await db.refresh(profile)

    await _notify_partner_status(
        db,
        user.id,
        title="Dropshipper Application Rejected",
        message=(
            f"Your dropshipping application for “{profile.shop_name}” was not approved. "
            f"Reason: {cleaned}"
        ),
    )
    return _partner_read(profile, user)


async def admin_suspend_partner(
    db: AsyncSession,
    profile_id: uuid.UUID,
    reason: str,
    actor: User,
) -> AdminDropshipperPartnerRead:
    profile, user = await _load_partner_pair(db, profile_id)
    cleaned = reason.strip()
    profile.status = DropshipperStatus.SUSPENDED.value
    if cleaned:
        profile.rejection_reason = cleaned

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_SUSPENDED,
        target_type="dropshipper_profile",
        target_id=str(profile.id),
        metadata={"user_id": str(user.id), "reason": cleaned},
    )
    await db.commit()
    await db.refresh(profile)

    await _notify_partner_status(
        db,
        user.id,
        title="Dropshipper Account Suspended",
        message=(
            f"Your dropshipping account “{profile.shop_name}” has been suspended."
            + (f" Reason: {cleaned}" if cleaned else "")
        ),
    )
    return _partner_read(profile, user)


async def admin_reactivate_partner(
    db: AsyncSession,
    profile_id: uuid.UUID,
    actor: User,
) -> AdminDropshipperPartnerRead:
    profile, user = await _load_partner_pair(db, profile_id)
    profile.status = DropshipperStatus.APPROVED.value
    profile.rejection_reason = None
    if profile.approved_at is None:
        profile.approved_at = datetime.now(UTC)
        profile.approved_by = actor.id

    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.DROPSHIPPER_REACTIVATED,
        target_type="dropshipper_profile",
        target_id=str(profile.id),
        metadata={"user_id": str(user.id), "shop_name": profile.shop_name},
    )
    await db.commit()
    await db.refresh(profile)

    await _notify_partner_status(
        db,
        user.id,
        title="Dropshipper Account Reactivated",
        message=(
            f"Your dropshipping account “{profile.shop_name}” has been reactivated. "
            "You can continue placing wholesale orders."
        ),
    )
    return _partner_read(profile, user)
