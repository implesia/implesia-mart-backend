from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, no_store
from app.core.exceptions import NotFoundError
from app.models.order import Order, OrderStatus
from app.schemas.common import Page, page_count
from app.schemas.customer import (
    CustomerDashboardStats,
    CustomerOrderDetail,
    CustomerOrderItemSummary,
    CustomerOrderSummary,
    OrderTrackingDetail,
    PurchasedProductItem,
)
from app.services import customer_purchased_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/orders", response_model=Page[CustomerOrderSummary])
async def list_customer_orders(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> Page[CustomerOrderSummary]:
    count_stmt = select(func.count(Order.id)).where(Order.user_id == user.id)
    total = (await db.scalar(count_stmt)) or 0

    offset = (page - 1) * page_size
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    orders = result.scalars().all()

    items = [
        CustomerOrderSummary(
            id=order.id,
            number=order.number,
            status=order.status,
            created_at=order.created_at,
            total=order.total,
            payment_method=order.payment_method,
            items_count=sum(item.quantity for item in order.items) or len(order.items),
            courier_name=order.courier_name,
            tracking_number=order.tracking_number,
            first_item_image=order.items[0].image_src if order.items else None,
            first_item_title=order.items[0].title if order.items else None,
        )
        for order in orders
    ]

    return Page(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


@router.get("/orders/{order_number}", response_model=CustomerOrderDetail)
async def get_customer_order(
    db: DbSession,
    user: CurrentUser,
    order_number: str,
) -> CustomerOrderDetail:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.number == order_number, Order.user_id == user.id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")

    return CustomerOrderDetail(
        id=order.id,
        number=order.number,
        status=order.status,
        created_at=order.created_at,
        delivered_at=order.delivered_at,
        customer_name=order.customer_name,
        phone=order.phone,
        district=order.district,
        area=order.area,
        address=order.address,
        subtotal=order.subtotal,
        shipping=order.shipping,
        total=order.total,
        coupon_discount=order.coupon_discount,
        manual_discount=order.manual_discount,
        paid_amount=order.paid_amount,
        due_amount=order.due_amount,
        payment_method=order.payment_method,
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        items=[
            CustomerOrderItemSummary(
                title=item.title,
                slug=item.slug,
                image_src=item.image_src,
                unit_price=item.unit_price,
                quantity=item.quantity,
                line_total=item.line_total,
                sku=item.sku,
            )
            for item in order.items
        ],
    )


@router.get("/dashboard-summary", response_model=CustomerDashboardStats)
async def get_dashboard_summary(
    db: DbSession,
    user: CurrentUser,
) -> CustomerDashboardStats:
    total_orders = (
        await db.scalar(select(func.count(Order.id)).where(Order.user_id == user.id))
    ) or 0

    active_statuses = [
        OrderStatus.NEW.value,
        OrderStatus.CONFIRMED.value,
        OrderStatus.PACKED.value,
        OrderStatus.SHIPPED.value,
    ]
    active_orders = (
        await db.scalar(
            select(func.count(Order.id)).where(
                Order.user_id == user.id, Order.status.in_(active_statuses)
            )
        )
    ) or 0

    non_revenue_statuses = [
        OrderStatus.CANCELLED.value,
        OrderStatus.RETURNED.value,
    ]
    total_spent = (
        await db.scalar(
            select(func.coalesce(func.sum(Order.total), 0)).where(
                Order.user_id == user.id, Order.status.notin_(non_revenue_statuses)
            )
        )
    ) or 0

    return CustomerDashboardStats(
        total_orders=int(total_orders),
        active_orders=int(active_orders),
        total_spent=int(total_spent),
        customer_name=user.full_name,
        phone=user.phone,
        email=user.email,
    )


@router.get("/purchased-products", response_model=list[PurchasedProductItem])
async def get_purchased_products(
    db: DbSession,
    user: CurrentUser,
) -> list[PurchasedProductItem]:
    return await customer_purchased_service.get_purchased_products(db, user.id)


@router.get("/orders/{order_number}/tracking", response_model=OrderTrackingDetail)
async def get_order_tracking(
    db: DbSession,
    user: CurrentUser,
    order_number: str,
) -> OrderTrackingDetail:
    return await customer_purchased_service.get_order_tracking(db, user.id, order_number)
