"""Dropshipper order quote, atomic placement, order listing, tracking & fraud-check."""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.models.courier import CourierShipment
from app.models.dropshipping import DropshipperProfile, DropshipperStatus, DropshipperTier
from app.models.order import (
    ActivityAction,
    Order,
    OrderIdempotency,
    OrderItem,
    OrderOrigin,
    OrderSource,
    OrderStatus,
)
from app.models.product import Product, ProductVariant, StockStatus
from app.models.user import User
from app.schemas.common import page_count
from app.schemas.customer import normalize_bd_phone
from app.schemas.customer_report import CourierCheck
from app.schemas.dropshipping import (
    DropshipOrderCreateRequest,
    DropshipOrderDetail,
    DropshipOrderItemRead,
    DropshipOrderListResponse,
    DropshipOrderQuoteLine,
    DropshipOrderQuoteRequest,
    DropshipOrderQuoteResponse,
    DropshipOrderSummary,
    DropshipOrderTrackingEvent,
    DropshipOrderTrackingResponse,
)
from app.services import (
    delivery_service,
    dropship_wallet_service,
    dropshipping_service,
    inventory_service,
    order_service,
    pricing_service,
    telegram_notify,
)
from app.services.courier import service as courier_service
from app.services.realtime_hub import STAFF_ORDERS_CHANNEL, realtime_hub


@dataclass
class _ValidatedLine:
    product: Product
    variant: ProductVariant | None
    quantity: int
    wholesale_price: int
    selling_price: int
    weight_grams: int
    sku: str
    title: str


def _dropship_actor(user: User) -> str:
    return f"dropshipper:{user.id}"


def _order_to_summary(order: Order) -> DropshipOrderSummary:
    items = list(order.items or [])
    return DropshipOrderSummary(
        id=order.id,
        number=order.number,
        status=order.status,
        customer_name=order.customer_name,
        phone=order.phone,
        district=order.district,
        area=order.area,
        customer_subtotal=order.subtotal,
        shipping=order.shipping,
        customer_total=order.total,
        wholesale_total=int(order.dropship_wholesale_total or 0),
        platform_fee=int(order.dropship_platform_fee or 0),
        profit_amount=int(order.dropship_profit_amount or 0),
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        items_count=sum(i.quantity for i in items) or len(items),
        first_item_title=items[0].title if items else None,
        first_item_image=items[0].image_src if items else None,
        created_at=order.created_at,
        delivered_at=order.delivered_at,
        returned_at=order.returned_at,
    )


def _order_to_detail(order: Order) -> DropshipOrderDetail:
    summary = _order_to_summary(order)
    return DropshipOrderDetail(
        **summary.model_dump(),
        address=order.address,
        note=order.notes,
        delivery_zone=order.delivery_zone,
        white_label_shop_name=order.white_label_shop_name,
        white_label_shop_phone=order.white_label_shop_phone,
        white_label_logo_url=order.white_label_logo_url,
        items=[
            DropshipOrderItemRead(
                id=item.id,
                product_id=item.product_id,
                variant_id=item.variant_id,
                title=item.title,
                slug=item.slug,
                image_src=item.image_src,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in (order.items or [])
        ],
    )


async def _validate_items_and_compute(
    db: AsyncSession,
    payload: DropshipOrderQuoteRequest,
    profile: DropshipperProfile,
) -> tuple[list[_ValidatedLine], DropshipOrderQuoteResponse]:
    settings = await dropshipping_service.get_settings_row(db)
    if not settings.enabled:
        raise PermissionDeniedError("Dropshipping program is currently disabled")
    if profile.status != DropshipperStatus.APPROVED.value:
        raise PermissionDeniedError("Only approved dropshippers can quote or place orders")

    product_ids = list({item.product_id for item in payload.items})
    products_list = (
        await db.scalars(select(Product).where(Product.id.in_(product_ids)))
    ).all()
    products_by_id = {p.id: p for p in products_list}

    variants_list = (
        await db.scalars(select(ProductVariant).where(ProductVariant.product_id.in_(product_ids)))
    ).all()
    variants_by_product: dict[uuid.UUID, list[ProductVariant]] = {}
    for v in variants_list:
        variants_by_product.setdefault(v.product_id, []).append(v)

    validated: list[_ValidatedLine] = []
    quote_lines: list[DropshipOrderQuoteLine] = []
    total_weight_grams = 0
    wholesale_total = 0
    customer_subtotal = 0

    for item in payload.items:
        product = products_by_id.get(item.product_id)
        if product is None or not product.published:
            raise UnprocessableError("One or more products are unavailable")
        if not product.allow_dropshipping:
            raise UnprocessableError(f"'{product.title}' is not enabled for dropshipping")
        if product.status != StockStatus.AVAILABLE.value:
            raise UnprocessableError(f"'{product.title}' is currently out of stock")

        variant: ProductVariant | None = None
        if product.has_variants:
            if item.variant_id is None:
                raise UnprocessableError(f"Please select a variant for '{product.title}'")
            variant = next(
                (v for v in variants_by_product.get(product.id, []) if v.id == item.variant_id),
                None,
            )
            if variant is None or not variant.is_active:
                raise UnprocessableError(f"Selected variant for '{product.title}' is unavailable")
            if variant.quantity is not None and variant.quantity < item.quantity:
                raise UnprocessableError(f"Not enough stock for '{product.title}'")
            wholesale_price = (
                variant.dropship_price
                if variant.dropship_price is not None
                else product.dropship_price
            )
            weight_grams = (
                variant.weight_grams
                if variant.weight_grams is not None
                else (product.weight_grams or 0)
            )
            sku = variant.sku or ""
            label = " / ".join(variant.options.values()) if variant.options else ""
            title = f"{product.title} ({label})" if label else product.title
        else:
            if item.variant_id is not None:
                raise UnprocessableError(f"'{product.title}' does not use variants")
            if product.quantity is not None and product.quantity < item.quantity:
                raise UnprocessableError(f"Not enough stock for '{product.title}'")
            wholesale_price = product.dropship_price
            weight_grams = product.weight_grams or 0
            sku = ""
            title = product.title

        if wholesale_price is None:
            raise UnprocessableError(f"'{product.title}' does not have a dropship price configured")

        if item.selling_price < wholesale_price:
            raise UnprocessableError(
                f"Selling price for '{product.title}' (৳{item.selling_price}) "
                f"cannot be below wholesale price (৳{wholesale_price})"
            )
        if product.min_sell_price is not None and item.selling_price < product.min_sell_price:
            raise UnprocessableError(
                f"Selling price for '{product.title}' must be at least ৳{product.min_sell_price}"
            )
        if product.max_sell_price is not None and item.selling_price > product.max_sell_price:
            raise UnprocessableError(
                f"Selling price for '{product.title}' cannot exceed ৳{product.max_sell_price}"
            )

        line_wholesale = wholesale_price * item.quantity
        line_selling = item.selling_price * item.quantity
        wholesale_total += line_wholesale
        customer_subtotal += line_selling
        total_weight_grams += max(0, int(weight_grams)) * item.quantity

        validated.append(
            _ValidatedLine(
                product=product,
                variant=variant,
                quantity=item.quantity,
                wholesale_price=wholesale_price,
                selling_price=item.selling_price,
                weight_grams=max(0, int(weight_grams)),
                sku=sku,
                title=title,
            )
        )
        quote_lines.append(
            DropshipOrderQuoteLine(
                product_id=product.id,
                variant_id=variant.id if variant else None,
                title=title,
                slug=product.slug,
                image_src=product.image_src,
                sku=sku,
                quantity=item.quantity,
                wholesale_price=wholesale_price,
                selling_price=item.selling_price,
                wholesale_total=line_wholesale,
                selling_total=line_selling,
                weight_grams=max(0, int(weight_grams)),
            )
        )

    rates = await delivery_service.fees(db)
    zone, _base, available = delivery_service.price_for(
        payload.district, payload.area, payload.delivery_zone, rates
    )
    if not available:
        raise UnprocessableError("Delivery is not available for this location")

    breakdown = delivery_service.calculate_weight_shipping(
        zone, total_weight_grams, rates
    )
    shipping = breakdown.total_fee
    weight_surcharge = breakdown.extra_weight_fee
    platform_fee = (
        int(round(wholesale_total * settings.platform_fee_percent / 100))
        + settings.packaging_fee_flat
    )
    customer_total = customer_subtotal + shipping
    profit_amount = customer_subtotal - wholesale_total - platform_fee

    # Check soft warnings for quote UI
    blocked_reason: str | None = None
    if profile.available_balance < settings.negative_wallet_limit:
        blocked_reason = (
            f"Available wallet balance (৳{profile.available_balance}) is below the "
            f"৳{settings.negative_wallet_limit} limit. Clear dues via Wallet Top-Up."
        )
    elif profile.tier == DropshipperTier.NEW.value:
        active_orders = await dropship_wallet_service.count_active_dropship_orders(
            db, profile.user_id
        )
        if active_orders >= settings.new_seller_max_active_orders:
            blocked_reason = (
                f"New seller limit reached ({active_orders}/"
                f"{settings.new_seller_max_active_orders} active orders)."
            )

    quote = DropshipOrderQuoteResponse(
        lines=quote_lines,
        delivery_zone=zone,
        total_weight_grams=total_weight_grams,
        shipping=shipping,
        weight_surcharge=weight_surcharge,
        wholesale_total=wholesale_total,
        platform_fee=platform_fee,
        customer_subtotal=customer_subtotal,
        customer_total=customer_total,
        profit_amount=profit_amount,
        can_place_order=blocked_reason is None,
        blocked_reason=blocked_reason,
    )
    return validated, quote


async def quote_order(
    db: AsyncSession,
    user: User,
    payload: DropshipOrderQuoteRequest,
) -> DropshipOrderQuoteResponse:
    unlocked = await dropship_wallet_service.settle_matured_pending_profits(db, user.id)
    if unlocked != 0:
        await db.commit()

    profile = await dropship_wallet_service._lock_profile_by_user(db, user.id)
    if profile is None:
        raise PermissionDeniedError("Dropshipper profile not found")

    _lines, quote = await _validate_items_and_compute(db, payload, profile)
    return quote


async def _load_dropship_order(
    db: AsyncSession, order_id: uuid.UUID
) -> Order:
    order = (
        await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def _replay(db: AsyncSession, actor: str, key: str) -> Order | None:
    existing = (
        await db.execute(select(OrderIdempotency).where(OrderIdempotency.idempotency_key == key))
    ).scalar_one_or_none()
    if existing is None:
        return None
    if existing.actor != actor:
        raise ConflictError("This idempotency key was already used")
    return await _load_dropship_order(db, existing.order_id)


async def create_order(
    db: AsyncSession,
    user: User,
    payload: DropshipOrderCreateRequest,
    idempotency_key: str,
    background: BackgroundTasks | None = None,
) -> DropshipOrderDetail:
    key = order_service.require_idempotency_key(idempotency_key)
    actor = _dropship_actor(user)
    existing = await _replay(db, actor, key)
    if existing is not None:
        return _order_to_detail(existing)

    telegram_notify.discard_low_stock(db)
    inventory_service.clear_pending_sales(db)

    await dropship_wallet_service.settle_matured_pending_profits(db, user.id)

    settings = await dropshipping_service.get_settings_row(db)
    if not settings.enabled:
        raise PermissionDeniedError("Dropshipping program is currently disabled")

    profile = await dropship_wallet_service._lock_profile_by_user(db, user.id)
    if profile is None or profile.status != DropshipperStatus.APPROVED.value:
        raise PermissionDeniedError("Only approved dropshippers can place orders")

    # 1. Negative Wallet Limit check
    if profile.available_balance < settings.negative_wallet_limit:
        raise UnprocessableError(
            f"Your available wallet balance (৳{profile.available_balance}) is below the "
            f"allowed limit (৳{settings.negative_wallet_limit}). Please clear dues via "
            "Wallet Top-Up before placing new orders."
        )

    # 2. New-Seller Trust Limit check
    if profile.tier == DropshipperTier.NEW.value:
        active_orders = await dropship_wallet_service.count_active_dropship_orders(db, user.id)
        if active_orders >= settings.new_seller_max_active_orders:
            raise UnprocessableError(
                f"New seller limit reached: maximum {settings.new_seller_max_active_orders} "
                f"active orders allowed until {settings.trusted_delivery_threshold} orders "
                "are delivered."
            )

    validated, quote = await _validate_items_and_compute(db, payload, profile)

    phone = payload.phone.strip()
    with contextlib.suppress(ValueError):
        phone = normalize_bd_phone(phone)

    rules = await pricing_service.store_rules(db)
    order_items: list[OrderItem] = []
    for line in validated:
        _priced_line, title, slug, image_src, sku = await order_service._claim(
            db,
            line.product,
            line.variant,
            line.quantity,
            rules,
            enforce_limits=False,
        )
        order_items.append(
            OrderItem(
                product_id=line.product.id,
                variant_id=line.variant.id if line.variant else None,
                title=line.title or title,
                slug=slug,
                image_src=image_src,
                sku=line.sku or sku,
                unit_price=line.selling_price,
                regular_price=line.selling_price,
                quantity=line.quantity,
                line_total=line.selling_price * line.quantity,
                unit_cost=line.product.cost_price,
            )
        )

    number = await order_service._number(db)
    order = Order(
        number=number,
        source=OrderSource.DIRECT.value,
        status=OrderStatus.NEW.value,
        origin=OrderOrigin.ONLINE.value,
        channel="dropship",
        dropshipper_id=user.id,
        user_id=None,
        customer_name=payload.customer_name,
        phone=phone,
        district=payload.district,
        area=payload.area,
        address=payload.address,
        notes=payload.note,
        delivery_zone=quote.delivery_zone,
        subtotal=quote.customer_subtotal,
        shipping=quote.shipping,
        total=quote.customer_total,
        total_weight_grams=quote.total_weight_grams,
        due_amount=quote.customer_total,
        payment_method="cod",
        dropship_wholesale_total=quote.wholesale_total,
        dropship_platform_fee=quote.platform_fee,
        dropship_profit_amount=quote.profit_amount,
        white_label_shop_name=profile.shop_name,
        white_label_shop_phone=profile.shop_phone,
        white_label_logo_url=profile.shop_logo_url,
        items=order_items,
    )
    db.add(order)
    await db.flush()

    order_service.log_activity(
        db,
        order.id,
        user.id,
        ActivityAction.CREATED,
        f"Dropship order placed by {profile.shop_name}",
        {
            "origin": OrderOrigin.ONLINE.value,
            "channel": "dropship",
            "dropshipper_id": str(user.id),
            "shop_name": profile.shop_name,
        },
    )
    inventory_service.attach_pending_sales(db, order.id)
    db.add(OrderIdempotency(actor=actor, idempotency_key=key, order_id=order.id))

    order_id = order.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        telegram_notify.discard_low_stock(db)
        replayed = await _replay(db, actor, key)
        if replayed is not None:
            return _order_to_detail(replayed)
        raise ConflictError("Could not place the order. Try again.") from None

    db.expire_all()
    loaded = await _load_dropship_order(db, order_id)

    if background is not None:
        await telegram_notify.notify_new_order(db, background, loaded)
        from app.services import push_service

        if push_service.is_configured():
            staff_ids = await push_service.staff_ids_with_module_read(db, "orders")
            if staff_ids:
                push_service.schedule_push_to_users(
                    background,
                    staff_ids,
                    "admin",
                    push_service.build_push_payload(
                        title=f"New Dropship Order #{loaded.number}",
                        body=f"{profile.shop_name} · {loaded.customer_name} · ৳{int(loaded.total)}",
                        url=f"/admin/orders/{loaded.id}",
                        tag=f"implesia-order-{loaded.id}",
                        scope="admin",
                        can_quick_reply=False,
                    ),
                )
    telegram_notify.flush_low_stock(db, background)
    with contextlib.suppress(Exception):
        await realtime_hub.publish(
            STAFF_ORDERS_CHANNEL,
            "order.new",
            {
                "id": str(loaded.id),
                "number": loaded.number,
                "status": loaded.status,
                "origin": loaded.origin,
                "channel": loaded.channel,
                "customer_name": loaded.customer_name,
                "total": loaded.total,
                "payment_method": loaded.payment_method,
                "created_at": loaded.created_at.isoformat(),
            },
        )
    return _order_to_detail(loaded)


async def list_orders(
    db: AsyncSession,
    user: User,
    *,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> DropshipOrderListResponse:
    conds: list[Any] = [Order.dropshipper_id == user.id]
    if status:
        conds.append(Order.status == status)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        conds.append(
            func.lower(Order.number).like(term)
            | func.lower(Order.customer_name).like(term)
            | func.lower(Order.phone).like(term)
        )

    total = int(await db.scalar(select(func.count(Order.id)).where(*conds)) or 0)
    orders = (
        await db.scalars(
            select(Order)
            .options(selectinload(Order.items))
            .where(*conds)
            .order_by(Order.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    return DropshipOrderListResponse(
        items=[_order_to_summary(o) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def get_order(
    db: AsyncSession, user: User, order_number: str
) -> DropshipOrderDetail:
    order = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.number == order_number, Order.dropshipper_id == user.id)
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")
    return _order_to_detail(order)


async def get_order_tracking(
    db: AsyncSession, user: User, order_number: str
) -> DropshipOrderTrackingResponse:
    order = (
        await db.execute(
            select(Order).where(Order.number == order_number, Order.dropshipper_id == user.id)
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")

    shipment = (
        await db.execute(
            select(CourierShipment)
            .where(CourierShipment.order_id == order.id)
            .order_by(CourierShipment.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    events: list[DropshipOrderTrackingEvent] = []
    if shipment is not None and isinstance(shipment.tracking_events, list):
        for ev in shipment.tracking_events:
            if isinstance(ev, dict):
                events.append(
                    DropshipOrderTrackingEvent(
                        status=str(ev.get("status") or ""),
                        message=str(ev.get("message") or ""),
                        timestamp=ev.get("timestamp"),
                        source=str(ev.get("source") or "courier"),
                    )
                )

    return DropshipOrderTrackingResponse(
        order_number=order.number,
        order_status=order.status,
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        consignment_id=shipment.consignment_id if shipment else None,
        delivery_status=shipment.delivery_status if shipment else None,
        return_status=shipment.return_status if shipment else None,
        is_final=bool(shipment.is_final) if shipment else False,
        is_return_received=bool(shipment.is_return_received) if shipment else False,
        last_synced_at=shipment.last_synced_at if shipment else None,
        events=events,
    )


async def fraud_check(
    db: AsyncSession,
    phone: str,
    *,
    refresh: bool = False,
) -> CourierCheck:
    normalized = phone.strip()
    try:
        normalized = normalize_bd_phone(normalized)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc

    if refresh:
        return await courier_service.refresh_courier_check(db, normalized)
    return await courier_service.read_courier_check(db, normalized)
