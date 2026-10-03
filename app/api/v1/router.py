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
from app.api.v1.endpoints.faqs import callout as faq_callout
from app.api.v1.endpoints.faqs import categories as faq_categories
from app.api.v1.endpoints.faqs import help as faq_help
from app.api.v1.endpoints.faqs import hero as faq_hero
from app.api.v1.endpoints.faqs import items as faq_items
from app.api.v1.endpoints.faqs import listing as faq_listing
from app.api.v1.endpoints.home import banner as home_banner
from app.api.v1.endpoints.home import category as home_category
from app.api.v1.endpoints.home import faq as home_faq
from app.api.v1.endpoints.home import featured as home_featured
from app.api.v1.endpoints.home import newsletter as home_newsletter
from app.api.v1.endpoints.home import review as home_review
from app.api.v1.endpoints.home import showcase as home_showcase
from app.api.v1.endpoints.home import trust as home_trust
from app.api.v1.endpoints.privacy import collection as privacy_collection
from app.api.v1.endpoints.privacy import contents as privacy_contents
from app.api.v1.endpoints.privacy import hero as privacy_hero
from app.api.v1.endpoints.privacy import introduction as privacy_introduction
from app.api.v1.endpoints.privacy import rights as privacy_rights
from app.api.v1.endpoints.privacy import sharing as privacy_sharing
from app.api.v1.endpoints.privacy import support as privacy_support
from app.api.v1.endpoints.privacy import usage as privacy_usage
from app.api.v1.endpoints.shipping import block as shipping_block
from app.api.v1.endpoints.shipping import contents as shipping_contents
from app.api.v1.endpoints.shipping import faq as shipping_faq
from app.api.v1.endpoints.shipping import hero as shipping_hero
from app.api.v1.endpoints.shipping import payment as shipping_payment
from app.api.v1.endpoints.shipping import refund as shipping_refund
from app.api.v1.endpoints.shipping import returns as shipping_returns
from app.api.v1.endpoints.shipping import support as shipping_support
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
api_router.include_router(faq_hero.public_router, prefix="/pages/faqs/hero", tags=["pages:faqs"])
api_router.include_router(
    faq_hero.admin_router, prefix="/admin/pages/faqs/hero", tags=["admin:pages:faqs"]
)
api_router.include_router(
    faq_categories.public_router, prefix="/pages/faqs/categories", tags=["pages:faqs"]
)
api_router.include_router(
    faq_categories.admin_router,
    prefix="/admin/pages/faqs/categories",
    tags=["admin:pages:faqs"],
)
api_router.include_router(
    faq_listing.public_router, prefix="/pages/faqs/listing", tags=["pages:faqs"]
)
api_router.include_router(
    faq_listing.admin_router, prefix="/admin/pages/faqs/listing", tags=["admin:pages:faqs"]
)
api_router.include_router(
    faq_callout.public_router, prefix="/pages/faqs/callout", tags=["pages:faqs"]
)
api_router.include_router(
    faq_callout.admin_router, prefix="/admin/pages/faqs/callout", tags=["admin:pages:faqs"]
)
api_router.include_router(faq_items.public_router, prefix="/pages/faqs/items", tags=["pages:faqs"])
api_router.include_router(
    faq_items.admin_router, prefix="/admin/pages/faqs/items", tags=["admin:pages:faqs"]
)
api_router.include_router(faq_help.public_router, prefix="/pages/faqs/help", tags=["pages:faqs"])
api_router.include_router(
    faq_help.admin_router, prefix="/admin/pages/faqs/help", tags=["admin:pages:faqs"]
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
api_router.include_router(
    shipping_hero.public_router, prefix="/pages/shipping/hero", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_hero.admin_router, prefix="/admin/pages/shipping/hero", tags=["admin:pages:shipping"]
)
api_router.include_router(
    shipping_contents.public_router, prefix="/pages/shipping/contents", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_contents.admin_router,
    prefix="/admin/pages/shipping/contents",
    tags=["admin:pages:shipping"],
)
api_router.include_router(
    shipping_block.public_router, prefix="/pages/shipping/shipping", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_block.admin_router,
    prefix="/admin/pages/shipping/shipping",
    tags=["admin:pages:shipping"],
)
api_router.include_router(
    shipping_payment.public_router, prefix="/pages/shipping/payment", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_payment.admin_router,
    prefix="/admin/pages/shipping/payment",
    tags=["admin:pages:shipping"],
)
api_router.include_router(
    shipping_returns.public_router, prefix="/pages/shipping/returns", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_returns.admin_router,
    prefix="/admin/pages/shipping/returns",
    tags=["admin:pages:shipping"],
)
api_router.include_router(
    shipping_refund.public_router, prefix="/pages/shipping/refund", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_refund.admin_router,
    prefix="/admin/pages/shipping/refund",
    tags=["admin:pages:shipping"],
)
api_router.include_router(
    shipping_support.public_router, prefix="/pages/shipping/support", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_support.admin_router,
    prefix="/admin/pages/shipping/support",
    tags=["admin:pages:shipping"],
)
api_router.include_router(
    shipping_faq.public_router, prefix="/pages/shipping/faq", tags=["pages:shipping"]
)
api_router.include_router(
    shipping_faq.admin_router,
    prefix="/admin/pages/shipping/faq",
    tags=["admin:pages:shipping"],
)
api_router.include_router(
    privacy_hero.public_router, prefix="/pages/privacy/hero", tags=["pages:privacy"]
)
api_router.include_router(
    privacy_hero.admin_router,
    prefix="/admin/pages/privacy/hero",
    tags=["admin:pages:privacy"],
)
api_router.include_router(
    privacy_contents.public_router, prefix="/pages/privacy/contents", tags=["pages:privacy"]
)
api_router.include_router(
    privacy_contents.admin_router,
    prefix="/admin/pages/privacy/contents",
    tags=["admin:pages:privacy"],
)
api_router.include_router(
    privacy_introduction.public_router,
    prefix="/pages/privacy/introduction",
    tags=["pages:privacy"],
)
api_router.include_router(
    privacy_introduction.admin_router,
    prefix="/admin/pages/privacy/introduction",
    tags=["admin:pages:privacy"],
)
api_router.include_router(
    privacy_collection.public_router,
    prefix="/pages/privacy/collection",
    tags=["pages:privacy"],
)
api_router.include_router(
    privacy_collection.admin_router,
    prefix="/admin/pages/privacy/collection",
    tags=["admin:pages:privacy"],
)
api_router.include_router(
    privacy_usage.public_router, prefix="/pages/privacy/usage", tags=["pages:privacy"]
)
api_router.include_router(
    privacy_usage.admin_router,
    prefix="/admin/pages/privacy/usage",
    tags=["admin:pages:privacy"],
)
api_router.include_router(
    privacy_sharing.public_router, prefix="/pages/privacy/sharing", tags=["pages:privacy"]
)
api_router.include_router(
    privacy_sharing.admin_router,
    prefix="/admin/pages/privacy/sharing",
    tags=["admin:pages:privacy"],
)
api_router.include_router(
    privacy_rights.public_router, prefix="/pages/privacy/rights", tags=["pages:privacy"]
)
api_router.include_router(
    privacy_rights.admin_router,
    prefix="/admin/pages/privacy/rights",
    tags=["admin:pages:privacy"],
)
api_router.include_router(
    privacy_support.public_router, prefix="/pages/privacy/support", tags=["pages:privacy"]
)
api_router.include_router(
    privacy_support.admin_router,
    prefix="/admin/pages/privacy/support",
    tags=["admin:pages:privacy"],
)
