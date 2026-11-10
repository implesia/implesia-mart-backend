"""Asia/Dhaka calendar expressions that stay inside SQL.

Dhaka is UTC+6 all year. PostgreSQL compares the timestamptz directly.
SQLite stores the offset in the text, so a raw comparison sorts by the
written clock and puts 18:00 UTC on the previous Dhaka day. Those filters
go through datetime(), which reads the offset and returns UTC.
"""

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

SHOP = ZoneInfo("Asia/Dhaka")


def dialect_name(db: AsyncSession) -> str:
    bind = db.bind
    if bind is None:
        raise RuntimeError("The database session has no engine")
    return bind.dialect.name


def dhaka_day(column: Any, dialect: str) -> ColumnElement[date]:
    if dialect == "postgresql":
        return cast(func.timezone("Asia/Dhaka", column), Date)
    return func.date(column, "+6 hours")


def dhaka_hour(column: Any, dialect: str) -> ColumnElement[datetime]:
    if dialect == "postgresql":
        return func.date_trunc("hour", func.timezone("Asia/Dhaka", column))
    return func.strftime("%Y-%m-%d %H:00:00", column, "+6 hours")


def utc_text(moment: datetime) -> str:
    """UTC clock, no offset, so it matches SQLite datetime()."""
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def at_or_after(column: Any, moment: datetime, dialect: str) -> ColumnElement[bool]:
    if dialect == "postgresql":
        return column >= moment
    return func.datetime(column) >= utc_text(moment)


def before(column: Any, moment: datetime, dialect: str) -> ColumnElement[bool]:
    if dialect == "postgresql":
        return column < moment
    return func.datetime(column) < utc_text(moment)
