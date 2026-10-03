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
from app.api.v1.endpoints.about import cta as about_cta
from app.api.v1.endpoints.about import dress as about_dress
from app.api.v1.endpoints.about import hero as about_hero
from app.api.v1.endpoints.about import mission as about_mission
from app.api.v1.endpoints.about import stats as about_stats
from app.api.v1.endpoints.about import steps as about_steps
from app.api.v1.endpoints.about import story as about_story
from app.api.v1.endpoints.about import values as about_values
from app.api.v1.endpoints.blogs import categories as blog_categories
from app.api.v1.endpoints.blogs import cta as blog_cta
from app.api.v1.endpoints.blogs import hero as blog_hero
from app.api.v1.endpoints.blogs import listing as blog_listing
from app.api.v1.endpoints.blogs import posts as blog_posts
from app.api.v1.endpoints.blogs import related as blog_related
from app.api.v1.endpoints.contact import details as contact_details
from app.api.v1.endpoints.contact import faq as contact_faq
from app.api.v1.endpoints.contact import form as contact_form
from app.api.v1.endpoints.contact import hero as contact_hero
from app.api.v1.endpoints.contact import support as contact_support
from app.api.v1.endpoints.home import banner as home_banner
from app.api.v1.endpoints.home import category as home_category
from app.api.v1.endpoints.home import faq as home_faq
from app.api.v1.endpoints.home import featured as home_featured
from app.api.v1.endpoints.home import newsletter as home_newsletter
from app.api.v1.endpoints.home import review as home_review
from app.api.v1.endpoints.home import showcase as home_showcase
from app.api.v1.endpoints.home import trust as home_trust
from app.api.v1.endpoints.sustainability import commitment as sustainability_commitment
from app.api.v1.endpoints.sustainability import cta as sustainability_cta
from app.api.v1.endpoints.sustainability import durability as sustainability_durability
from app.api.v1.endpoints.sustainability import hero as sustainability_hero
from app.api.v1.endpoints.sustainability import impact as sustainability_impact
from app.api.v1.endpoints.sustainability import origin as sustainability_origin
from app.api.v1.endpoints.sustainability import quality as sustainability_quality

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
api_router.include_router(about_cta.public_router, prefix="/pages/about/cta", tags=["pages:about"])
api_router.include_router(
    about_cta.admin_router, prefix="/admin/pages/about/cta", tags=["admin:pages:about"]
)
api_router.include_router(
    contact_hero.public_router, prefix="/pages/contact/hero", tags=["pages:contact"]
)
api_router.include_router(
    contact_hero.admin_router, prefix="/admin/pages/contact/hero", tags=["admin:pages:contact"]
)
api_router.include_router(
    contact_form.public_router, prefix="/pages/contact/form", tags=["pages:contact"]
)
api_router.include_router(
    contact_form.admin_router, prefix="/admin/pages/contact/form", tags=["admin:pages:contact"]
)
api_router.include_router(
    contact_details.public_router, prefix="/pages/contact/details", tags=["pages:contact"]
)
api_router.include_router(
    contact_details.admin_router,
    prefix="/admin/pages/contact/details",
    tags=["admin:pages:contact"],
)
api_router.include_router(
    contact_support.public_router, prefix="/pages/contact/support", tags=["pages:contact"]
)
api_router.include_router(
    contact_support.admin_router,
    prefix="/admin/pages/contact/support",
    tags=["admin:pages:contact"],
)
api_router.include_router(
    contact_faq.public_router, prefix="/pages/contact/faq", tags=["pages:contact"]
)
api_router.include_router(
    contact_faq.admin_router, prefix="/admin/pages/contact/faq", tags=["admin:pages:contact"]
)
api_router.include_router(
    blog_hero.public_router, prefix="/pages/blogs/hero", tags=["pages:blogs"]
)
api_router.include_router(
    blog_hero.admin_router, prefix="/admin/pages/blogs/hero", tags=["admin:pages:blogs"]
)
api_router.include_router(
    blog_categories.public_router, prefix="/pages/blogs/categories", tags=["pages:blogs"]
)
api_router.include_router(
    blog_categories.admin_router,
    prefix="/admin/pages/blogs/categories",
    tags=["admin:pages:blogs"],
)
api_router.include_router(
    blog_listing.public_router, prefix="/pages/blogs/listing", tags=["pages:blogs"]
)
api_router.include_router(
    blog_listing.admin_router, prefix="/admin/pages/blogs/listing", tags=["admin:pages:blogs"]
)
api_router.include_router(
    blog_posts.public_router, prefix="/pages/blogs/posts", tags=["pages:blogs"]
)
api_router.include_router(
    blog_posts.admin_router, prefix="/admin/pages/blogs/posts", tags=["admin:pages:blogs"]
)
api_router.include_router(
    blog_related.public_router, prefix="/pages/blogs/related", tags=["pages:blogs"]
)
api_router.include_router(
    blog_related.admin_router, prefix="/admin/pages/blogs/related", tags=["admin:pages:blogs"]
)
api_router.include_router(
    blog_cta.public_router, prefix="/pages/blogs/cta", tags=["pages:blogs"]
)
api_router.include_router(
    blog_cta.admin_router, prefix="/admin/pages/blogs/cta", tags=["admin:pages:blogs"]
)
api_router.include_router(
    sustainability_hero.public_router,
    prefix="/pages/sustainability/hero",
    tags=["pages:sustainability"],
)
api_router.include_router(
    sustainability_hero.admin_router,
    prefix="/admin/pages/sustainability/hero",
    tags=["admin:pages:sustainability"],
)
api_router.include_router(
    sustainability_impact.public_router,
    prefix="/pages/sustainability/impact",
    tags=["pages:sustainability"],
)
api_router.include_router(
    sustainability_impact.admin_router,
    prefix="/admin/pages/sustainability/impact",
    tags=["admin:pages:sustainability"],
)
api_router.include_router(
    sustainability_origin.public_router,
    prefix="/pages/sustainability/origin",
    tags=["pages:sustainability"],
)
api_router.include_router(
    sustainability_origin.admin_router,
    prefix="/admin/pages/sustainability/origin",
    tags=["admin:pages:sustainability"],
)
api_router.include_router(
    sustainability_commitment.public_router,
    prefix="/pages/sustainability/commitment",
    tags=["pages:sustainability"],
)
api_router.include_router(
    sustainability_commitment.admin_router,
    prefix="/admin/pages/sustainability/commitment",
    tags=["admin:pages:sustainability"],
)
api_router.include_router(
    sustainability_quality.public_router,
    prefix="/pages/sustainability/quality",
    tags=["pages:sustainability"],
)
api_router.include_router(
    sustainability_quality.admin_router,
    prefix="/admin/pages/sustainability/quality",
    tags=["admin:pages:sustainability"],
)
api_router.include_router(
    sustainability_durability.public_router,
    prefix="/pages/sustainability/durability",
    tags=["pages:sustainability"],
)
api_router.include_router(
    sustainability_durability.admin_router,
    prefix="/admin/pages/sustainability/durability",
    tags=["admin:pages:sustainability"],
)
api_router.include_router(
    sustainability_cta.public_router,
    prefix="/pages/sustainability/cta",
    tags=["pages:sustainability"],
)
api_router.include_router(
    sustainability_cta.admin_router,
    prefix="/admin/pages/sustainability/cta",
    tags=["admin:pages:sustainability"],
)
