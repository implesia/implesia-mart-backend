"""The top menu the storefront had before it became editable (preserved, not new copy).

Used when the `site_header` table has no row, and when a saved row is unusable. The storefront
keeps a mirror of this (`headerNav` fallback in lib/header-view.ts) for when the API is down.
"""

from typing import Any

DEFAULT_ITEMS: list[dict[str, Any]] = [
    {"label": "হোম", "href": "/", "enabled": True},
    {"label": "প্রোডাক্ট", "href": "/products", "enabled": True},
    {"label": "আমাদের সম্পর্কে", "href": "/about-us", "enabled": True},
    {"label": "সাসটেইনেবিলিটি", "href": "/sustainability", "enabled": True},
    {"label": "যোগাযোগ", "href": "/contact-us", "enabled": True},
    {"label": "ব্লগ", "href": "/blogs", "enabled": True},
]
