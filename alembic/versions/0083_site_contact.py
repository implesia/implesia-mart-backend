"""central site contact settings (phone, WhatsApp, email)

Revision ID: 0083
Revises: 0082
Create Date: 2026-10-27

Creates `site_contact`, one row holding the store's phone, WhatsApp number and email. The
storefront header, footer, floating chat button, contact page, product WhatsApp button and
the contact / about call-to-action links all follow it.

What this does to existing data:
 * Creates the table and seeds ONE row with the new official values
   (phone 01580569129, WhatsApp 01580569129, email implesiamart@gmail.com).
 * Replaces the retired legacy contact values in existing CMS text (varchar/text columns and
   JSON columns) with the new ones. Only these exact strings are touched:
     "+880 1516-527932" / "+880 1516 527932" / "8801516527932" / "01516527932"
       -> the new number, in the same shape (display, wa.me digits, local),
     "implesiaitltd@gmail.com" -> "implesiamart@gmail.com".
   Every other row and column is left alone. The replacement is idempotent.

Rollback limits (downgrade): drops `site_contact`, so the contact values an editor saved
after upgrading are lost and the built-in defaults (the same new values) apply again. The
legacy strings replaced in CMS text are NOT restored: the old number and email are retired,
so putting them back would be wrong, and they are not recoverable from the table alone.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_LOCAL = "01580569129"
NEW_EMAIL = "implesiamart@gmail.com"

# (old, new): longest/most specific first.
_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("+880 1516-527932", NEW_LOCAL),
    ("+880 1516 527932", NEW_LOCAL),
    ("8801516527932", "8801580569129"),
    ("01516527932", NEW_LOCAL),
    ("implesiaitltd@gmail.com", NEW_EMAIL),
)
_SKIP_TABLES = ("alembic_version", "site_contact", "users", "audit_events", "refresh_tokens")


def _expr(column: str, kind: str) -> str:
    """SQL that rewrites every legacy value inside one column expression."""
    expr = f'"{column}"::text' if kind in ("json", "jsonb") else f'"{column}"'
    for old, new in _REPLACEMENTS:
        expr = f"replace({expr}, '{old}', '{new}')"
    return f"{expr}::{kind}" if kind in ("json", "jsonb") else expr


def _scrub_legacy_contacts(bind: sa.Connection) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c "
            "JOIN information_schema.tables t ON t.table_schema = c.table_schema "
            "AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE' "
            "WHERE c.table_schema = current_schema() "
            "AND c.data_type IN ('character varying', 'text', 'json', 'jsonb') "
            "AND c.table_name NOT IN :skip"
        ).bindparams(sa.bindparam("skip", expanding=True)),
        {"skip": list(_SKIP_TABLES)},
    ).all()
    patterns = " OR ".join(f"{{c}} LIKE '%{old}%'" for old, _ in _REPLACEMENTS)
    for table, column, data_type in rows:
        if table.startswith("pg_") or table == "alembic_version":
            continue
        kind = "jsonb" if data_type == "jsonb" else "json" if data_type == "json" else "text"
        col = f'"{column}"::text' if kind in ("json", "jsonb") else f'"{column}"'
        where = patterns.replace("{c}", col)
        bind.execute(
            sa.text(f'UPDATE "{table}" SET "{column}" = {_expr(column, kind)} WHERE {where}')
        )


def upgrade() -> None:
    op.create_table(
        "site_contact",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("phone", sa.String(length=11), nullable=False),
        sa.Column("whatsapp", sa.String(length=11), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_contact")),
    )
    op.create_index(op.f("ix_site_contact_slug"), "site_contact", ["slug"], unique=True)
    op.execute(
        sa.text(
            "INSERT INTO site_contact (id, slug, phone, whatsapp, email) "
            "VALUES (:id, 'main', :phone, :whatsapp, :email)"
        ).bindparams(id=uuid.uuid4(), phone=NEW_LOCAL, whatsapp=NEW_LOCAL, email=NEW_EMAIL)
    )
    _scrub_legacy_contacts(op.get_bind())


def downgrade() -> None:
    op.drop_index(op.f("ix_site_contact_slug"), table_name="site_contact")
    op.drop_table("site_contact")
