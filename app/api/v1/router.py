from fastapi import APIRouter

from app.api.v1.endpoints import (
    about_cta,
    about_dress,
    about_hero,
    about_mission,
    about_stats,
    about_steps,
    about_story,
    about_values,
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
from app.api.v1.endpoints.home import banner as home_banner
from app.api.v1.endpoints.home import category as home_category
from app.api.v1.endpoints.home import faq as home_faq
from app.api.v1.endpoints.home import featured as home_featured
from app.api.v1.endpoints.home import newsletter as home_newsletter
from app.api.v1.endpoints.home import review as home_review
from app.api.v1.endpoints.home import showcase as home_showcase
from app.api.v1.endpoints.home import trust as home_trust

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
api_router.include_router(home_banner.public_router, prefix="/home/banner", tags=["home:banner"])
api_router.include_router(
    home_banner.admin_router, prefix="/admin/home/banner", tags=["admin:home:banner"]
)
api_router.include_router(home_trust.public_router, prefix="/home/trust", tags=["home:trust"])
api_router.include_router(
    home_trust.admin_router, prefix="/admin/home/trust", tags=["admin:home:trust"]
)
api_router.include_router(
    home_category.public_router, prefix="/home/categories", tags=["home:categories"]
)
api_router.include_router(
    home_category.admin_router, prefix="/admin/home/categories", tags=["admin:home:categories"]
)
api_router.include_router(
    home_featured.public_router, prefix="/home/featured", tags=["home:featured"]
)
api_router.include_router(
    home_featured.admin_router, prefix="/admin/home/featured", tags=["admin:home:featured"]
)
api_router.include_router(
    home_showcase.public_router, prefix="/home/showcase", tags=["home:showcase"]
)
api_router.include_router(
    home_showcase.admin_router, prefix="/admin/home/showcase", tags=["admin:home:showcase"]
)
api_router.include_router(home_review.public_router, prefix="/home/reviews", tags=["home:reviews"])
api_router.include_router(
    home_review.admin_router, prefix="/admin/home/reviews", tags=["admin:home:reviews"]
)
api_router.include_router(home_faq.public_router, prefix="/home/faq", tags=["home:faq"])
api_router.include_router(home_faq.admin_router, prefix="/admin/home/faq", tags=["admin:home:faq"])
api_router.include_router(
    home_newsletter.public_router, prefix="/home/newsletter", tags=["home:newsletter"]
)
api_router.include_router(
    home_newsletter.admin_router, prefix="/admin/home/newsletter", tags=["admin:home:newsletter"]
)
api_router.include_router(
    about_hero.public_router, prefix="/pages/about/hero", tags=["pages:about"]
)
api_router.include_router(
    about_hero.admin_router, prefix="/admin/pages/about/hero", tags=["admin:pages:about"]
)
api_router.include_router(
    about_stats.public_router, prefix="/pages/about/stats", tags=["pages:about"]
)
api_router.include_router(
    about_stats.admin_router, prefix="/admin/pages/about/stats", tags=["admin:pages:about"]
)
api_router.include_router(
    about_story.public_router, prefix="/pages/about/stories", tags=["pages:about"]
)
api_router.include_router(
    about_story.admin_router, prefix="/admin/pages/about/stories", tags=["admin:pages:about"]
)
api_router.include_router(
    about_dress.public_router, prefix="/pages/about/dresses", tags=["pages:about"]
)
api_router.include_router(
    about_dress.admin_router, prefix="/admin/pages/about/dresses", tags=["admin:pages:about"]
)
api_router.include_router(
    about_mission.public_router, prefix="/pages/about/mission", tags=["pages:about"]
)
api_router.include_router(
    about_mission.admin_router, prefix="/admin/pages/about/mission", tags=["admin:pages:about"]
)
api_router.include_router(
    about_values.public_router, prefix="/pages/about/values", tags=["pages:about"]
)
api_router.include_router(
    about_values.admin_router, prefix="/admin/pages/about/values", tags=["admin:pages:about"]
)
api_router.include_router(
    about_steps.public_router, prefix="/pages/about/steps", tags=["pages:about"]
)
api_router.include_router(
    about_steps.admin_router, prefix="/admin/pages/about/steps", tags=["admin:pages:about"]
)
api_router.include_router(
    about_cta.public_router, prefix="/pages/about/cta", tags=["pages:about"]
)
api_router.include_router(
    about_cta.admin_router, prefix="/admin/pages/about/cta", tags=["admin:pages:about"]
)
