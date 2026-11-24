"""seed default roles and any role already stored on users.role

Revision ID: 0108
Revises: 0107
Create Date: 2026-11-24

Additive and idempotent. Inserts the system roles, the legacy slugs
``super_admin``, ``admin``, and ``staff``, and every distinct ``users.role``
value that does not already have a ``roles`` row.

``INSERT ... ON CONFLICT (slug) DO NOTHING`` leaves existing role rows and
every ``users`` row unchanged. Nothing is dropped, renamed, or updated.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of the 0107 system roles. ON CONFLICT keeps a row that already exists.
_SYSTEM_ROLES: tuple[dict[str, object], ...] = (
    {
        "slug": "superadmin",
        "label": "Superadmin",
        "description": (
            "Full system owner with unrestricted access to all admin modules, "
            "staff accounts, RBAC matrix, audit logs, and impact-checked deletes."
        ),
        "category": "staff",
        "admin_access": True,
        "is_system": True,
    },
    {
        "slug": "editor",
        "label": "Editor",
        "description": (
            "Operational staff role with customizable module permissions for "
            "orders, catalog, inventory, reviews, coupons, and CMS."
        ),
        "category": "staff",
        "admin_access": True,
        "is_system": True,
    },
    {
        "slug": "viewer",
        "label": "Viewer",
        "description": (
            "Observer/analyst staff role. Defaults to read-only across store "
            "modules and can be fine-tuned per module by Superadmin."
        ),
        "category": "staff",
        "admin_access": True,
        "is_system": True,
    },
    {
        "slug": "customer",
        "label": "Customer",
        "description": (
            "Storefront shopper account. Permanently blocked from /admin and "
            "all staff APIs; limited to personal storefront orders and profile."
        ),
        "category": "storefront",
        "admin_access": False,
        "is_system": True,
    },
)

# Keep these slugs aligned with app.services.permission_service.LEGACY_ROLE_SLUGS.
# They do not grant admin access. A later edit of a real role row is not done here.
_LEGACY_ROLES: tuple[dict[str, object], ...] = (
    {
        "slug": "super_admin",
        "label": "Super admin (legacy)",
        "description": "Legacy users.role value. Does not grant admin access.",
        "category": "staff",
        "admin_access": False,
        "is_system": False,
    },
    {
        "slug": "admin",
        "label": "Admin (legacy)",
        "description": "Legacy users.role value. Does not grant admin access.",
        "category": "staff",
        "admin_access": False,
        "is_system": False,
    },
    {
        "slug": "staff",
        "label": "Staff (legacy)",
        "description": "Legacy users.role value. Does not grant admin access.",
        "category": "staff",
        "admin_access": False,
        "is_system": False,
    },
)

_INSERT = sa.text(
    """
    INSERT INTO roles (
        id, slug, label, description, category, admin_access, is_system
    )
    VALUES (
        :id, :slug, :label, :description, :category, :admin_access, :is_system
    )
    ON CONFLICT (slug) DO NOTHING
    """
)


def _insert(bind: sa.Connection, row: dict[str, object]) -> None:
    bind.execute(_INSERT, {"id": uuid.uuid4(), **row})


def upgrade() -> None:
    bind = op.get_bind()
    for row in (*_SYSTEM_ROLES, *_LEGACY_ROLES):
        _insert(bind, row)

    used = list(
        bind.execute(
            sa.text(
                "SELECT DISTINCT role FROM users "
                "WHERE role IS NOT NULL AND btrim(role) <> ''"
            )
        ).scalars()
    )
    known = {row[0] for row in bind.execute(sa.text("SELECT slug FROM roles"))}
    for slug in used:
        if slug in known or len(slug) > 50:
            continue
        _insert(
            bind,
            {
                "slug": slug,
                "label": slug[:80],
                "description": "Role already stored on users.role.",
                "category": "staff",
                "admin_access": False,
                "is_system": False,
            },
        )
        known.add(slug)


def downgrade() -> None:
    # Removing a seeded row could orphan users.role. Leave every row in place.
    pass
