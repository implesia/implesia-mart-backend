"""inquiries: visitor messages and newsletter sign-ups

Revision ID: 0073
Revises: 0072
Create Date: 2026-10-15

One table for every storefront submission (contact form, newsletter, product
questions). Every visitor field is optional; no IP address is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inquiries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("name", sa.String(80), nullable=False, server_default=""),
        sa.Column("email", sa.String(254), nullable=False, server_default=""),
        sa.Column("phone", sa.String(15), nullable=False, server_default=""),
        sa.Column("subject", sa.String(160), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("admin_note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "handled_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("public_id", name="uq_inquiries_public_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_inquiries_idempotency_key"),
        sa.CheckConstraint(
            "type IN ('newsletter','contact','product_inquiry','order_help','other')",
            name="ck_inquiries_type",
        ),
        sa.CheckConstraint(
            "status IN ('new','in_progress','resolved')", name="ck_inquiries_status"
        ),
    )
    op.create_index("ix_inquiries_email", "inquiries", ["email"])
    op.create_index("ix_inquiries_phone", "inquiries", ["phone"])
    op.create_index("ix_inquiries_status_created", "inquiries", ["status", "created_at"])
    op.create_index("ix_inquiries_type_created", "inquiries", ["type", "created_at"])


def downgrade() -> None:
    op.drop_table("inquiries")
