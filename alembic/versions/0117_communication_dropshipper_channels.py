"""Add dropshipper_id and widen conversations.type for marketplace channels.

Revision ID: 0117
Revises: 0116
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0117"
down_revision: str | None = "0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES_CHECK = "type IN ('customer_support', 'seller_support', 'customer_seller')"
_NEW_TYPES_CHECK = (
    "type IN ("
    "'customer_support', 'seller_support', 'dropshipper_support', "
    "'customer_seller', 'customer_dropshipper'"
    ")"
)


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        with op.batch_alter_table("conversations", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("dropshipper_id", postgresql.UUID(as_uuid=True), nullable=True)
            )
            batch_op.create_foreign_key(
                op.f("fk_conversations_dropshipper_id_users"),
                "users",
                ["dropshipper_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.drop_constraint(op.f("ck_conversations_type_known"), type_="check")
            batch_op.create_check_constraint(
                op.f("ck_conversations_type_known"),
                _NEW_TYPES_CHECK,
            )
    else:
        op.add_column(
            "conversations",
            sa.Column("dropshipper_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            op.f("fk_conversations_dropshipper_id_users"),
            "conversations",
            "users",
            ["dropshipper_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_constraint(
            op.f("ck_conversations_type_known"),
            "conversations",
            type_="check",
        )
        op.create_check_constraint(
            op.f("ck_conversations_type_known"),
            "conversations",
            _NEW_TYPES_CHECK,
        )

    op.create_index(
        op.f("ix_conversations_dropshipper_id"),
        "conversations",
        ["dropshipper_id"],
    )
    op.create_index(
        op.f("ix_conversations_dropshipper_last_msg"),
        "conversations",
        ["dropshipper_id", sa.text("last_message_at DESC")],
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    op.drop_index(op.f("ix_conversations_dropshipper_last_msg"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_dropshipper_id"), table_name="conversations")

    if is_sqlite:
        with op.batch_alter_table("conversations", schema=None) as batch_op:
            batch_op.drop_constraint(op.f("ck_conversations_type_known"), type_="check")
            batch_op.create_check_constraint(
                op.f("ck_conversations_type_known"),
                _OLD_TYPES_CHECK,
            )
            batch_op.drop_constraint(
                op.f("fk_conversations_dropshipper_id_users"),
                type_="foreignkey",
            )
            batch_op.drop_column("dropshipper_id")
    else:
        op.drop_constraint(
            op.f("ck_conversations_type_known"),
            "conversations",
            type_="check",
        )
        op.create_check_constraint(
            op.f("ck_conversations_type_known"),
            "conversations",
            _OLD_TYPES_CHECK,
        )
        op.drop_constraint(
            op.f("fk_conversations_dropshipper_id_users"),
            "conversations",
            type_="foreignkey",
        )
        op.drop_column("conversations", "dropshipper_id")
