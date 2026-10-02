from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_cart,
    admin_delivery,
    admin_orders,
    admin_products,
    auth,
    cart,
    dashboard,
    delivery,
    orders,
    products,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(dashboard.router, prefix="/admin/dashboard", tags=["admin:dashboard"])
api_router.include_router(admin_products.router, prefix="/admin/products", tags=["admin:products"])
api_router.include_router(cart.router, prefix="/cart", tags=["cart"])
api_router.include_router(delivery.router, prefix="/delivery", tags=["delivery"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(admin_delivery.router, prefix="/admin/delivery", tags=["admin:delivery"])
api_router.include_router(admin_cart.router, prefix="/admin/carts", tags=["admin:carts"])
api_router.include_router(admin_orders.router, prefix="/admin/orders", tags=["admin:orders"])
