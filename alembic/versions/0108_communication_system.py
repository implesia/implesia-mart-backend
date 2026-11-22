"""add communication system tables (conversations, messages, conversation_read_states)

Revision ID: 0108
Revises: 0107
Create Date: 2026-11-22

Additive-only:
* conversations(id, type, customer_id, seller_id, order_id, product_id, assigned_staff_id,
  subject, status, last_message_at, last_message_preview, created_at, updated_at)
  with high-scale composite DESC indexes
* messages(id, conversation_id, sender_id, sender_role, body, attachment_url,
  is_internal_note, created_at) with composite keyset pagination index
* conversation_read_states(conversation_id, user_id, last_read_at)
* Seeds default RBAC role_permissions for module 'communication'
  (editor=read_write, viewer=read_only)
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "seller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_message_preview",
            sa.String(length=240),
            nullable=False,
            server_default="",
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
        sa.CheckConstraint(
            "type IN ('customer_support', 'seller_support', 'customer_seller')",
            name="ck_conversations_type_known",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'pending', 'resolved', 'closed')",
            name="ck_conversations_status_known",
        ),
    )
    op.create_index("ix_conversations_customer_id", "conversations", ["customer_id"])
    op.create_index("ix_conversations_seller_id", "conversations", ["seller_id"])
    op.create_index("ix_conversations_order_id", "conversations", ["order_id"])
    op.create_index("ix_conversations_product_id", "conversations", ["product_id"])
    op.create_index("ix_conversations_assigned_staff_id", "conversations", ["assigned_staff_id"])
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])
    op.create_index(
        "ix_conversations_customer_last_msg",
        "conversations",
        ["customer_id", sa.text("last_message_at DESC")],
    )
    op.create_index(
        "ix_conversations_seller_last_msg",
        "conversations",
        ["seller_id", sa.text("last_message_at DESC")],
    )
    op.create_index(
        "ix_conversations_type_status_last_msg",
        "conversations",
        ["type", "status", sa.text("last_message_at DESC")],
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sender_role", sa.String(length=50), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.Column("attachment_url", sa.String(length=500), nullable=True),
        sa.Column(
            "is_internal_note",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])
    op.create_index(
        "ix_messages_conv_created_id",
        "messages",
        ["conversation_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "conversation_read_states",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Seed default RBAC permissions for the new 'communication' module if role_permissions exists.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "role_permissions" in tables and "roles" in tables:
        for role_slug, access_level in (("editor", "read_write"), ("viewer", "read_only")):
            role_exists = bind.execute(
                sa.text("SELECT 1 FROM roles WHERE slug = :slug"),
                {"slug": role_slug},
            ).first()
            perm_exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM role_permissions "
                    "WHERE role = :role AND module_key = 'communication'"
                ),
                {"role": role_slug},
            ).first()
            if role_exists and not perm_exists:
                bind.execute(
                    sa.text(
                        "INSERT INTO role_permissions (id, role, module_key, access_level) "
                        "VALUES (:id, :role, 'communication', :access_level)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "role": role_slug,
                        "access_level": access_level,
                    },
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "role_permissions" in set(inspector.get_table_names()):
        bind.execute(sa.text("DELETE FROM role_permissions WHERE module_key = 'communication'"))

    op.drop_table("conversation_read_states")

    op.drop_index("ix_messages_conv_created_id", table_name="messages")
    op.drop_index("ix_messages_sender_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_type_status_last_msg", table_name="conversations")
    op.drop_index("ix_conversations_seller_last_msg", table_name="conversations")
    op.drop_index("ix_conversations_customer_last_msg", table_name="conversations")
    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    op.drop_index("ix_conversations_assigned_staff_id", table_name="conversations")
    op.drop_index("ix_conversations_product_id", table_name="conversations")
    op.drop_index("ix_conversations_order_id", table_name="conversations")
    op.drop_index("ix_conversations_seller_id", table_name="conversations")
    op.drop_index("ix_conversations_customer_id", table_name="conversations")
    op.drop_table("conversations")
