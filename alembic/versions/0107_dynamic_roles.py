"""add dynamic roles table and convert users.role to FK string

Revision ID: 0107
Revises: 0106
Create Date: 2026-11-22

Additive & schema evolution:
* Creates roles table (id, slug, label, description, category, admin_access, is_system)
* Seeds the 4 system roles: superadmin, editor, viewer, customer (is_system=True)
* Converts users.role from PostgreSQL enum user_role to VARCHAR(50) with FK -> roles(slug)
* Adds ix_users_role and FK role_permissions.role -> roles(slug) ON DELETE CASCADE
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0107"
down_revision: str | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYSTEM_ROLES = [
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
]


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    roles_table = op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=20), nullable=False, server_default="staff"),
        sa.Column("admin_access", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_roles_slug"),
        sa.CheckConstraint("category IN ('staff', 'storefront')", name="ck_roles_category"),
    )
    op.create_index("ix_roles_slug", "roles", ["slug"], unique=True)

    op.bulk_insert(
        roles_table,
        [{"id": uuid.uuid4(), **row} for row in _SYSTEM_ROLES],
    )

    if is_pg:
        op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50) USING role::text")
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'viewer'")
        op.create_index("ix_users_role", "users", ["role"])
        op.create_foreign_key(
            "fk_users_role_roles",
            "users",
            "roles",
            ["role"],
            ["slug"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        )
        op.execute("ALTER TABLE role_permissions ALTER COLUMN role TYPE VARCHAR(50)")
        op.create_foreign_key(
            "fk_role_permissions_role_roles",
            "role_permissions",
            "roles",
            ["role"],
            ["slug"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        )
    else:
        op.create_index("ix_users_role", "users", ["role"])


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.drop_constraint("fk_role_permissions_role_roles", "role_permissions", type_="foreignkey")
        op.drop_constraint("fk_users_role_roles", "users", type_="foreignkey")
        op.drop_index("ix_users_role", table_name="users")
        op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role")
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'viewer'::user_role")
    else:
        op.drop_index("ix_users_role", table_name="users")

    op.drop_index("ix_roles_slug", table_name="roles")
    op.drop_table("roles")
