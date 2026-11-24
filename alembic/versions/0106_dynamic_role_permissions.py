"""add dynamic role_permissions table with default staff matrix

Revision ID: 0106
Revises: 0105
Create Date: 2026-11-22

Additive-only:
* role_permissions(id, role, module_key, access_level, updated_by, created_at, updated_at)
* uq_role_permissions_role_module on (role, module_key)
* ck_role_permissions_access_level enforcing ('none', 'read_only', 'read_write', 'full')
* Seeds default permissions for editor and viewer across all 12 admin modules.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_SEED: list[tuple[str, str, str]] = [
    # Editor defaults
    ("editor", "dashboard", "read_only"),
    ("editor", "reports", "read_only"),
    ("editor", "orders", "read_write"),
    ("editor", "products", "read_write"),
    ("editor", "inventory", "read_write"),
    ("editor", "reviews", "read_write"),
    ("editor", "inquiries", "read_write"),
    ("editor", "cart", "read_only"),
    ("editor", "coupons_pricing", "read_write"),
    ("editor", "cms", "read_write"),
    ("editor", "rbac", "none"),
    ("editor", "audit_deletes", "none"),
    # Viewer defaults
    ("viewer", "dashboard", "read_only"),
    ("viewer", "reports", "read_only"),
    ("viewer", "orders", "read_only"),
    ("viewer", "products", "read_only"),
    ("viewer", "inventory", "read_only"),
    ("viewer", "reviews", "read_only"),
    ("viewer", "inquiries", "read_only"),
    ("viewer", "cart", "read_only"),
    ("viewer", "coupons_pricing", "read_only"),
    ("viewer", "cms", "read_only"),
    ("viewer", "rbac", "none"),
    ("viewer", "audit_deletes", "none"),
]


def upgrade() -> None:
    role_permissions = op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("module_key", sa.String(length=64), nullable=False),
        sa.Column("access_level", sa.String(length=20), nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("role", "module_key", name="uq_role_permissions_role_module"),
        sa.CheckConstraint(
            "access_level IN ('none', 'read_only', 'read_write', 'full')",
            name="ck_role_permissions_access_level",
        ),
    )
    op.create_index("ix_role_permissions_role", "role_permissions", ["role"])
    op.create_index("ix_role_permissions_module_key", "role_permissions", ["module_key"])
    op.create_index("ix_role_permissions_updated_by", "role_permissions", ["updated_by"])

    op.bulk_insert(
        role_permissions,
        [
            {
                "id": uuid.uuid4(),
                "role": role,
                "module_key": module_key,
                "access_level": access_level,
                "updated_by": None,
            }
            for role, module_key, access_level in _DEFAULT_SEED
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_role_permissions_updated_by", table_name="role_permissions")
    op.drop_index("ix_role_permissions_module_key", table_name="role_permissions")
    op.drop_index("ix_role_permissions_role", table_name="role_permissions")
    op.drop_table("role_permissions")
