"""Phase 31: Additive dropshipping core schema, roles, permissions & wallet tables.

Revision ID: 0118
Revises: 0117
Create Date: 2026-11-28
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0118"
down_revision: str | None = "0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    id_sql = ":id" if is_sqlite else "CAST(:id AS UUID)"

    # 1. Seed system role `dropshipper` (admin_access=False, strictly non-staff)
    if is_sqlite:
        bind.execute(
            sa.text(
                f"""
                INSERT OR IGNORE INTO roles
                    (id, slug, label, description, category, admin_access, is_system)
                VALUES (
                    {id_sql},
                    'dropshipper',
                    'Dropshipper',
                    'Approved dropshipping partner account. Blocked from /admin and staff APIs.',
                    'storefront',
                    0,
                    1
                )
                """
            ),
            {"id": str(uuid.uuid4())},
        )
    else:
        bind.execute(
            sa.text(
                f"""
                INSERT INTO roles
                    (id, slug, label, description, category, admin_access, is_system)
                VALUES (
                    {id_sql},
                    'dropshipper',
                    'Dropshipper',
                    'Approved dropshipping partner account. Blocked from /admin and staff APIs.',
                    'storefront',
                    FALSE,
                    TRUE
                )
                ON CONFLICT (slug) DO NOTHING
                """
            ),
            {"id": str(uuid.uuid4())},
        )

    # Seed `dropshipping` module permissions for system staff roles
    for role_slug, access_level in (
        ("superadmin", "full"),
        ("editor", "read_write"),
        ("viewer", "read_only"),
    ):
        if is_sqlite:
            bind.execute(
                sa.text(
                    f"""
                    INSERT OR IGNORE INTO role_permissions (id, role, module_key, access_level)
                    VALUES ({id_sql}, :role, 'dropshipping', :access_level)
                    """
                ),
                {"id": str(uuid.uuid4()), "role": role_slug, "access_level": access_level},
            )
        else:
            bind.execute(
                sa.text(
                    f"""
                    INSERT INTO role_permissions (id, role, module_key, access_level)
                    VALUES ({id_sql}, :role, 'dropshipping', :access_level)
                    ON CONFLICT (role, module_key) DO NOTHING
                    """
                ),
                {"id": str(uuid.uuid4()), "role": role_slug, "access_level": access_level},
            )

    # 2. Additive columns on `products`
    if is_sqlite:
        with op.batch_alter_table("products", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "allow_dropshipping",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
            batch_op.add_column(sa.Column("dropship_price", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("min_sell_price", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("max_sell_price", sa.Integer(), nullable=True))
            batch_op.create_check_constraint(
                op.f("ck_products_dropship_price_non_negative"),
                "dropship_price IS NULL OR dropship_price >= 0",
            )
            batch_op.create_check_constraint(
                op.f("ck_products_min_sell_price_non_negative"),
                "min_sell_price IS NULL OR min_sell_price >= 0",
            )
            batch_op.create_check_constraint(
                op.f("ck_products_max_sell_price_non_negative"),
                "max_sell_price IS NULL OR max_sell_price >= 0",
            )
    else:
        op.add_column(
            "products",
            sa.Column(
                "allow_dropshipping",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.add_column("products", sa.Column("dropship_price", sa.Integer(), nullable=True))
        op.add_column("products", sa.Column("min_sell_price", sa.Integer(), nullable=True))
        op.add_column("products", sa.Column("max_sell_price", sa.Integer(), nullable=True))
        op.create_check_constraint(
            op.f("ck_products_dropship_price_non_negative"),
            "products",
            "dropship_price IS NULL OR dropship_price >= 0",
        )
        op.create_check_constraint(
            op.f("ck_products_min_sell_price_non_negative"),
            "products",
            "min_sell_price IS NULL OR min_sell_price >= 0",
        )
        op.create_check_constraint(
            op.f("ck_products_max_sell_price_non_negative"),
            "products",
            "max_sell_price IS NULL OR max_sell_price >= 0",
        )
    op.create_index(
        op.f("ix_products_allow_dropshipping"),
        "products",
        ["allow_dropshipping"],
    )

    # 3. Additive column on `product_variants`
    if is_sqlite:
        with op.batch_alter_table("product_variants", schema=None) as batch_op:
            batch_op.add_column(sa.Column("dropship_price", sa.Integer(), nullable=True))
            batch_op.create_check_constraint(
                op.f("ck_product_variants_dropship_price_non_negative"),
                "dropship_price IS NULL OR dropship_price >= 0",
            )
    else:
        op.add_column("product_variants", sa.Column("dropship_price", sa.Integer(), nullable=True))
        op.create_check_constraint(
            op.f("ck_product_variants_dropship_price_non_negative"),
            "product_variants",
            "dropship_price IS NULL OR dropship_price >= 0",
        )

    # 4. Additive columns on `orders`
    if is_sqlite:
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("dropshipper_id", postgresql.UUID(as_uuid=True), nullable=True)
            )
            batch_op.add_column(
                sa.Column("dropship_wholesale_total", sa.Integer(), nullable=True)
            )
            batch_op.add_column(sa.Column("dropship_profit_amount", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("dropship_platform_fee", sa.Integer(), nullable=True))
            batch_op.add_column(
                sa.Column("white_label_shop_name", sa.String(length=160), nullable=True)
            )
            batch_op.add_column(
                sa.Column("white_label_shop_phone", sa.String(length=32), nullable=True)
            )
            batch_op.add_column(
                sa.Column("white_label_logo_url", sa.String(length=500), nullable=True)
            )
            batch_op.create_foreign_key(
                op.f("fk_orders_dropshipper_id_users"),
                "users",
                ["dropshipper_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_check_constraint(
                op.f("ck_orders_dropship_wholesale_non_negative"),
                "dropship_wholesale_total IS NULL OR dropship_wholesale_total >= 0",
            )
            batch_op.create_check_constraint(
                op.f("ck_orders_dropship_platform_fee_non_negative"),
                "dropship_platform_fee IS NULL OR dropship_platform_fee >= 0",
            )
    else:
        op.add_column(
            "orders",
            sa.Column("dropshipper_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.add_column(
            "orders",
            sa.Column("dropship_wholesale_total", sa.Integer(), nullable=True),
        )
        op.add_column("orders", sa.Column("dropship_profit_amount", sa.Integer(), nullable=True))
        op.add_column("orders", sa.Column("dropship_platform_fee", sa.Integer(), nullable=True))
        op.add_column(
            "orders",
            sa.Column("white_label_shop_name", sa.String(length=160), nullable=True),
        )
        op.add_column(
            "orders",
            sa.Column("white_label_shop_phone", sa.String(length=32), nullable=True),
        )
        op.add_column(
            "orders",
            sa.Column("white_label_logo_url", sa.String(length=500), nullable=True),
        )
        op.create_foreign_key(
            op.f("fk_orders_dropshipper_id_users"),
            "orders",
            "users",
            ["dropshipper_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_check_constraint(
            op.f("ck_orders_dropship_wholesale_non_negative"),
            "orders",
            "dropship_wholesale_total IS NULL OR dropship_wholesale_total >= 0",
        )
        op.create_check_constraint(
            op.f("ck_orders_dropship_platform_fee_non_negative"),
            "orders",
            "dropship_platform_fee IS NULL OR dropship_platform_fee >= 0",
        )
    op.create_index(op.f("ix_orders_dropshipper_id"), "orders", ["dropshipper_id"])

    # 5. Create `dropshipping_settings` (singleton id = 1)
    op.create_table(
        "dropshipping_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("registration_fee", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "new_seller_max_active_orders", sa.Integer(), nullable=False, server_default="3"
        ),
        sa.Column("trusted_delivery_threshold", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("negative_wallet_limit", sa.Integer(), nullable=False, server_default="-200"),
        sa.Column("payout_unlock_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "require_cod_reconciled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("min_withdrawal_amount", sa.Integer(), nullable=False, server_default="500"),
        sa.Column(
            "rto_charge_mode",
            sa.String(length=32),
            nullable=False,
            server_default="order_shipping",
        ),
        sa.Column("rto_fixed_fee", sa.Integer(), nullable=False, server_default="130"),
        sa.Column("platform_fee_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("packaging_fee_flat", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dropshipping_settings")),
        sa.CheckConstraint("id = 1", name=op.f("ck_dropshipping_settings_singleton")),
        sa.CheckConstraint(
            "registration_fee >= 0",
            name=op.f("ck_dropshipping_settings_registration_fee_non_negative"),
        ),
        sa.CheckConstraint(
            "new_seller_max_active_orders >= 0",
            name=op.f("ck_dropshipping_settings_new_seller_max_active_orders_non_negative"),
        ),
        sa.CheckConstraint(
            "trusted_delivery_threshold >= 0",
            name=op.f("ck_dropshipping_settings_trusted_delivery_threshold_non_negative"),
        ),
        sa.CheckConstraint(
            "negative_wallet_limit <= 0",
            name=op.f("ck_dropshipping_settings_negative_wallet_limit_non_positive"),
        ),
        sa.CheckConstraint(
            "payout_unlock_days >= 0",
            name=op.f("ck_dropshipping_settings_payout_unlock_days_non_negative"),
        ),
        sa.CheckConstraint(
            "min_withdrawal_amount >= 0",
            name=op.f("ck_dropshipping_settings_min_withdrawal_amount_non_negative"),
        ),
        sa.CheckConstraint(
            "rto_charge_mode IN ('order_shipping', 'fixed')",
            name=op.f("ck_dropshipping_settings_rto_charge_mode_known"),
        ),
        sa.CheckConstraint(
            "rto_fixed_fee >= 0",
            name=op.f("ck_dropshipping_settings_rto_fixed_fee_non_negative"),
        ),
        sa.CheckConstraint(
            "platform_fee_percent >= 0 AND platform_fee_percent <= 100",
            name=op.f("ck_dropshipping_settings_platform_fee_percent_range"),
        ),
        sa.CheckConstraint(
            "packaging_fee_flat >= 0",
            name=op.f("ck_dropshipping_settings_packaging_fee_flat_non_negative"),
        ),
    )

    if is_sqlite:
        bind.execute(
            sa.text(
                """
                INSERT OR IGNORE INTO dropshipping_settings (
                    id, enabled, registration_fee, new_seller_max_active_orders,
                    trusted_delivery_threshold, negative_wallet_limit, payout_unlock_days,
                    require_cod_reconciled, min_withdrawal_amount, rto_charge_mode,
                    rto_fixed_fee, platform_fee_percent, packaging_fee_flat
                )
                VALUES (1, 1, 0, 3, 5, -200, 3, 0, 500, 'order_shipping', 130, 0, 0)
                """
            )
        )
    else:
        bind.execute(
            sa.text(
                """
                INSERT INTO dropshipping_settings (
                    id, enabled, registration_fee, new_seller_max_active_orders,
                    trusted_delivery_threshold, negative_wallet_limit, payout_unlock_days,
                    require_cod_reconciled, min_withdrawal_amount, rto_charge_mode,
                    rto_fixed_fee, platform_fee_percent, packaging_fee_flat
                )
                VALUES (1, TRUE, 0, 3, 5, -200, 3, FALSE, 500, 'order_shipping', 130, 0, 0)
                ON CONFLICT (id) DO NOTHING
                """
            )
        )

    # 6. Create `dropshipper_profiles`
    op.create_table(
        "dropshipper_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("tier", sa.String(length=24), nullable=False, server_default="new"),
        sa.Column("shop_slug", sa.String(length=80), nullable=False),
        sa.Column("shop_name", sa.String(length=160), nullable=False),
        sa.Column("shop_phone", sa.String(length=32), nullable=False),
        sa.Column("shop_logo_url", sa.String(length=500), nullable=True),
        sa.Column("shop_address", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("business_url", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("nid_number", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("nid_front_url", sa.String(length=500), nullable=True),
        sa.Column("nid_back_url", sa.String(length=500), nullable=True),
        sa.Column(
            "payout_method", sa.String(length=24), nullable=False, server_default="bkash"
        ),
        sa.Column(
            "payout_account_number", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column(
            "payout_account_name", sa.String(length=160), nullable=False, server_default=""
        ),
        sa.Column("bank_name", sa.String(length=120), nullable=True),
        sa.Column("bank_branch", sa.String(length=120), nullable=True),
        sa.Column("pending_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "locked_withdrawal_balance", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("total_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_withdrawn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dropshipper_profiles")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_dropshipper_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_dropshipper_profiles_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("user_id", name=op.f("uq_dropshipper_profiles_user_id")),
        sa.UniqueConstraint("shop_slug", name=op.f("uq_dropshipper_profiles_shop_slug")),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'suspended')",
            name=op.f("ck_dropshipper_profiles_status_known"),
        ),
        sa.CheckConstraint(
            "tier IN ('new', 'trusted', 'pro')",
            name=op.f("ck_dropshipper_profiles_tier_known"),
        ),
        sa.CheckConstraint(
            "payout_method IN ('bkash', 'nagad', 'rocket', 'bank')",
            name=op.f("ck_dropshipper_profiles_payout_method_known"),
        ),
        sa.CheckConstraint(
            "locked_withdrawal_balance >= 0 AND total_earned >= 0 AND total_withdrawn >= 0 "
            "AND delivered_count >= 0 AND returned_count >= 0",
            name=op.f("ck_dropshipper_profiles_counters_non_negative"),
        ),
    )
    op.create_index(
        op.f("ix_dropshipper_profiles_status"), "dropshipper_profiles", ["status"]
    )
    op.create_index(
        op.f("ix_dropshipper_profiles_shop_slug"), "dropshipper_profiles", ["shop_slug"]
    )

    # 7. Create `dropshipper_wallet_transactions`
    op.create_table(
        "dropshipper_wallet_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dropshipper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("topup_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_bucket", sa.String(length=24), nullable=False),
        sa.Column("unlock_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dropshipper_wallet_transactions")),
        sa.ForeignKeyConstraint(
            ["dropshipper_id"],
            ["users.id"],
            name=op.f("fk_dropshipper_wallet_transactions_dropshipper_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_dropshipper_wallet_transactions_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_dropshipper_wallet_transactions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_dropshipper_wallet_transactions_idempotency_key"),
        ),
        sa.CheckConstraint(
            "entry_type IN ('credit_pending', 'unlock_available', 'debit_rto', "
            "'debit_withdrawal_lock', 'withdrawal_paid', 'withdrawal_refund', "
            "'credit_topup', 'admin_adjustment')",
            name=op.f("ck_dropshipper_wallet_transactions_entry_type_known"),
        ),
        sa.CheckConstraint(
            "balance_bucket IN ('pending', 'available', 'locked')",
            name=op.f("ck_dropshipper_wallet_transactions_balance_bucket_known"),
        ),
    )
    op.create_index(
        op.f("ix_dropshipper_wallet_tx_dropshipper_id"),
        "dropshipper_wallet_transactions",
        ["dropshipper_id"],
    )
    op.create_index(
        op.f("ix_dropshipper_wallet_tx_unlock_at"),
        "dropshipper_wallet_transactions",
        ["unlock_at"],
    )
    op.create_index(
        op.f("ix_dropshipper_wallet_tx_dropshipper_created"),
        "dropshipper_wallet_transactions",
        ["dropshipper_id", sa.text("created_at DESC")],
    )

    # 8. Create `dropshipper_payout_requests`
    op.create_table(
        "dropshipper_payout_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dropshipper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("payout_method", sa.String(length=24), nullable=False),
        sa.Column("payout_account_number", sa.String(length=64), nullable=False),
        sa.Column(
            "payout_account_name", sa.String(length=160), nullable=False, server_default=""
        ),
        sa.Column("bank_name", sa.String(length=120), nullable=True),
        sa.Column("bank_branch", sa.String(length=120), nullable=True),
        sa.Column("transaction_id", sa.String(length=120), nullable=True),
        sa.Column("admin_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("processed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dropshipper_payout_requests")),
        sa.ForeignKeyConstraint(
            ["dropshipper_id"],
            ["users.id"],
            name=op.f("fk_dropshipper_payout_requests_dropshipper_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["processed_by"],
            ["users.id"],
            name=op.f("fk_dropshipper_payout_requests_processed_by_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name=op.f("ck_dropshipper_payout_requests_amount_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'rejected')",
            name=op.f("ck_dropshipper_payout_requests_status_known"),
        ),
        sa.CheckConstraint(
            "payout_method IN ('bkash', 'nagad', 'rocket', 'bank')",
            name=op.f("ck_dropshipper_payout_requests_payout_method_known"),
        ),
    )
    op.create_index(
        op.f("ix_dropshipper_payout_requests_dropshipper_id"),
        "dropshipper_payout_requests",
        ["dropshipper_id"],
    )
    op.create_index(
        op.f("ix_dropshipper_payout_requests_status"),
        "dropshipper_payout_requests",
        ["status"],
    )

    # 9. Create `dropshipper_topup_requests`
    op.create_table(
        "dropshipper_topup_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dropshipper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("sender_number", sa.String(length=32), nullable=False),
        sa.Column("transaction_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("admin_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("processed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dropshipper_topup_requests")),
        sa.ForeignKeyConstraint(
            ["dropshipper_id"],
            ["users.id"],
            name=op.f("fk_dropshipper_topup_requests_dropshipper_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["processed_by"],
            ["users.id"],
            name=op.f("fk_dropshipper_topup_requests_processed_by_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name=op.f("ck_dropshipper_topup_requests_amount_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_dropshipper_topup_requests_status_known"),
        ),
    )
    op.create_index(
        op.f("ix_dropshipper_topup_requests_dropshipper_id"),
        "dropshipper_topup_requests",
        ["dropshipper_id"],
    )
    op.create_index(
        op.f("ix_dropshipper_topup_requests_status"),
        "dropshipper_topup_requests",
        ["status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    op.drop_index(
        op.f("ix_dropshipper_topup_requests_status"),
        table_name="dropshipper_topup_requests",
    )
    op.drop_index(
        op.f("ix_dropshipper_topup_requests_dropshipper_id"),
        table_name="dropshipper_topup_requests",
    )
    op.drop_table("dropshipper_topup_requests")

    op.drop_index(
        op.f("ix_dropshipper_payout_requests_status"),
        table_name="dropshipper_payout_requests",
    )
    op.drop_index(
        op.f("ix_dropshipper_payout_requests_dropshipper_id"),
        table_name="dropshipper_payout_requests",
    )
    op.drop_table("dropshipper_payout_requests")

    op.drop_index(
        op.f("ix_dropshipper_wallet_tx_dropshipper_created"),
        table_name="dropshipper_wallet_transactions",
    )
    op.drop_index(
        op.f("ix_dropshipper_wallet_tx_unlock_at"),
        table_name="dropshipper_wallet_transactions",
    )
    op.drop_index(
        op.f("ix_dropshipper_wallet_tx_dropshipper_id"),
        table_name="dropshipper_wallet_transactions",
    )
    op.drop_table("dropshipper_wallet_transactions")

    op.drop_index(op.f("ix_dropshipper_profiles_shop_slug"), table_name="dropshipper_profiles")
    op.drop_index(op.f("ix_dropshipper_profiles_status"), table_name="dropshipper_profiles")
    op.drop_table("dropshipper_profiles")

    op.drop_table("dropshipping_settings")

    op.drop_index(op.f("ix_orders_dropshipper_id"), table_name="orders")
    if is_sqlite:
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.drop_constraint(
                op.f("ck_orders_dropship_platform_fee_non_negative"), type_="check"
            )
            batch_op.drop_constraint(
                op.f("ck_orders_dropship_wholesale_non_negative"), type_="check"
            )
            batch_op.drop_constraint(op.f("fk_orders_dropshipper_id_users"), type_="foreignkey")
            batch_op.drop_column("white_label_logo_url")
            batch_op.drop_column("white_label_shop_phone")
            batch_op.drop_column("white_label_shop_name")
            batch_op.drop_column("dropship_platform_fee")
            batch_op.drop_column("dropship_profit_amount")
            batch_op.drop_column("dropship_wholesale_total")
            batch_op.drop_column("dropshipper_id")
    else:
        op.drop_constraint(
            op.f("ck_orders_dropship_platform_fee_non_negative"), "orders", type_="check"
        )
        op.drop_constraint(
            op.f("ck_orders_dropship_wholesale_non_negative"), "orders", type_="check"
        )
        op.drop_constraint(op.f("fk_orders_dropshipper_id_users"), "orders", type_="foreignkey")
        op.drop_column("orders", "white_label_logo_url")
        op.drop_column("orders", "white_label_shop_phone")
        op.drop_column("orders", "white_label_shop_name")
        op.drop_column("orders", "dropship_platform_fee")
        op.drop_column("orders", "dropship_profit_amount")
        op.drop_column("orders", "dropship_wholesale_total")
        op.drop_column("orders", "dropshipper_id")

    if is_sqlite:
        with op.batch_alter_table("product_variants", schema=None) as batch_op:
            batch_op.drop_constraint(
                op.f("ck_product_variants_dropship_price_non_negative"), type_="check"
            )
            batch_op.drop_column("dropship_price")
    else:
        op.drop_constraint(
            op.f("ck_product_variants_dropship_price_non_negative"),
            "product_variants",
            type_="check",
        )
        op.drop_column("product_variants", "dropship_price")

    op.drop_index(op.f("ix_products_allow_dropshipping"), table_name="products")
    if is_sqlite:
        with op.batch_alter_table("products", schema=None) as batch_op:
            batch_op.drop_constraint(
                op.f("ck_products_max_sell_price_non_negative"), type_="check"
            )
            batch_op.drop_constraint(
                op.f("ck_products_min_sell_price_non_negative"), type_="check"
            )
            batch_op.drop_constraint(
                op.f("ck_products_dropship_price_non_negative"), type_="check"
            )
            batch_op.drop_column("max_sell_price")
            batch_op.drop_column("min_sell_price")
            batch_op.drop_column("dropship_price")
            batch_op.drop_column("allow_dropshipping")
    else:
        op.drop_constraint(
            op.f("ck_products_max_sell_price_non_negative"), "products", type_="check"
        )
        op.drop_constraint(
            op.f("ck_products_min_sell_price_non_negative"), "products", type_="check"
        )
        op.drop_constraint(
            op.f("ck_products_dropship_price_non_negative"), "products", type_="check"
        )
        op.drop_column("products", "max_sell_price")
        op.drop_column("products", "min_sell_price")
        op.drop_column("products", "dropship_price")
        op.drop_column("products", "allow_dropshipping")

    bind.execute(sa.text("DELETE FROM role_permissions WHERE module_key = 'dropshipping'"))
    bind.execute(
        sa.text(
            "DELETE FROM roles WHERE slug = 'dropshipper' "
            "AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'dropshipper')"
        )
    )
