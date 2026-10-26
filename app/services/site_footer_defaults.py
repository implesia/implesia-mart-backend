"""The footer the storefront had before it became editable (preserved, not new copy).

Used when the `site_footer` table has no row, and to fill any list an editor has not saved.
The storefront keeps a mirror of this for the case where the API is unreachable.
"""

from typing import Any

DEFAULTS: dict[str, Any] = {
    "brand_name": "Implesia Mart",
    "description": (
        "ট্রেন্ডিং গ্যাজেট আর হাতে তৈরি গর্জিয়াস ড্রেস — ক্যাশ অন ডেলিভারিতে সারাদেশে, নিশ্চিন্তে কিনুন।"
    ),
    "logo_src": "",
    "logo_alt": "",
    "address": "",
    "copyright_text": "© {year} · সর্বস্বত্ব সংরক্ষিত",
    "show_contact": True,
    "show_social": True,
    "show_whatsapp_cta": True,
    "sections": [
        {
            "title": "Shop",
            "enabled": True,
            "links": [
                {"label": "সব প্রোডাক্ট", "href": "/products", "enabled": True},
                {
                    "label": "Trending Gadgets",
                    "href": "/products?category=gadgets",
                    "enabled": True,
                },
                {
                    "label": "গর্জিয়াস ড্রেস",
                    "href": "/products?category=fashion",
                    "enabled": True,
                },
                {"label": "গাইড ও ব্লগ", "href": "/blogs", "enabled": True},
            ],
        },
        {
            "title": "Company",
            "enabled": True,
            "links": [
                {"label": "আমাদের সম্পর্কে", "href": "/about-us", "enabled": True},
                {"label": "সাসটেইনেবিলিটি", "href": "/sustainability", "enabled": True},
                {"label": "যোগাযোগ", "href": "/contact-us", "enabled": True},
                {"label": "ব্লগ", "href": "/blogs", "enabled": True},
            ],
        },
        {
            "title": "Support",
            "enabled": True,
            "links": [
                {"label": "আমার অর্ডার", "href": "/order-status", "enabled": True},
                {"label": "প্রশ্নোত্তর", "href": "/faqs", "enabled": True},
                {"label": "শিপিং ও রিটার্ন", "href": "/shipping-returns", "enabled": True},
                {"label": "গোপনীয়তা নীতি", "href": "/privacy-policy", "enabled": True},
                {"label": "চেকআউট", "href": "/checkout", "enabled": True},
            ],
        },
    ],
    "trust_points": [
        {"icon": "local_shipping", "label": "সারাদেশে ডেলিভারি", "enabled": True},
        {"icon": "payments", "label": "ক্যাশ অন ডেলিভারি", "enabled": True},
        {"icon": "assignment_return", "label": "৩ দিনের ইজি রিটার্ন", "enabled": True},
    ],
    "legal_links": [
        {"label": "গোপনীয়তা", "href": "/privacy-policy", "enabled": True},
        {"label": "শিপিং", "href": "/shipping-returns", "enabled": True},
        {"label": "আমার অর্ডার", "href": "/order-status", "enabled": True},
        {"label": "প্রশ্নোত্তর", "href": "/faqs", "enabled": True},
    ],
}
