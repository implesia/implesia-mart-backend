"""add communication system tables (conversations, messages, conversation_read_states)

Revision ID: 0110
Revises: 0109
Create Date: 2026-11-22

Renumbered from 0108 on 2026-11-24. ``0108`` is the role seed and ``0109`` is
``courier_check_results``. This revision stays the single head.

Additive-only. Creates new tables and seeds ``role_permissions`` rows for the
new ``communication`` module. Does not drop, rename, or update existing tables,
columns, or rows.

Names that are already in the naming-convention form are wrapped in ``op.f()``.
A bare name would be prefixed again (the 0097/0098 failure).

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

revision: str = "0110"
down_revision: str | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_staff_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
            name=op.f("fk_conversations_customer_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["seller_id"],
            ["users.id"],
            name=op.f("fk_conversations_seller_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_conversations_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_conversations_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_staff_id"],
            ["users.id"],
            name=op.f("fk_conversations_assigned_staff_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "type IN ('customer_support', 'seller_support', 'customer_seller')",
            name=op.f("ck_conversations_type_known"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'pending', 'resolved', 'closed')",
            name=op.f("ck_conversations_status_known"),
        ),
    )
    op.create_index(
        op.f("ix_conversations_customer_id"), "conversations", ["customer_id"]
    )
    op.create_index(op.f("ix_conversations_seller_id"), "conversations", ["seller_id"])
    op.create_index(op.f("ix_conversations_order_id"), "conversations", ["order_id"])
    op.create_index(op.f("ix_conversations_product_id"), "conversations", ["product_id"])
    op.create_index(
        op.f("ix_conversations_assigned_staff_id"),
        "conversations",
        ["assigned_staff_id"],
    )
    op.create_index(
        op.f("ix_conversations_last_message_at"), "conversations", ["last_message_at"]
    )
    op.create_index(
        op.f("ix_conversations_customer_last_msg"),
        "conversations",
        ["customer_id", sa.text("last_message_at DESC")],
    )
    op.create_index(
        op.f("ix_conversations_seller_last_msg"),
        "conversations",
        ["seller_id", sa.text("last_message_at DESC")],
    )
    op.create_index(
        op.f("ix_conversations_type_status_last_msg"),
        "conversations",
        ["type", "status", sa.text("last_message_at DESC")],
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["users.id"],
            name=op.f("fk_messages_sender_id_users"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_messages_sender_id"), "messages", ["sender_id"])
    op.create_index(
        op.f("ix_messages_conv_created_id"),
        "messages",
        ["conversation_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "conversation_read_states",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id",
            "user_id",
            name=op.f("pk_conversation_read_states"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_read_states_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_conversation_read_states_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    # user_id is the second primary-key column, so the PK does not index it.
    op.create_index(
        op.f("ix_conversation_read_states_user_id"),
        "conversation_read_states",
        ["user_id"],
    )

    # Seed default RBAC permissions for the new 'communication' module if role_permissions exists.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "role_permissions" in tables and "roles" in tables:
        # PostgreSQL rejects a text parameter for a uuid column. SQLite stores the id as text.
        id_sql = "CAST(:id AS UUID)" if bind.dialect.name == "postgresql" else ":id"
        insert_permission = sa.text(
            "INSERT INTO role_permissions (id, role, module_key, access_level) "
            f"VALUES ({id_sql}, :role, 'communication', :access_level)"
        )
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
                    insert_permission,
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

    op.drop_index(
        op.f("ix_conversation_read_states_user_id"),
        table_name="conversation_read_states",
    )
    op.drop_table("conversation_read_states")

    op.drop_index(op.f("ix_messages_conv_created_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_sender_id"), table_name="messages")
    op.drop_table("messages")

    op.drop_index(op.f("ix_conversations_type_status_last_msg"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_seller_last_msg"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_customer_last_msg"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_last_message_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_assigned_staff_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_product_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_order_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_seller_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_customer_id"), table_name="conversations")
    op.drop_table("conversations")
