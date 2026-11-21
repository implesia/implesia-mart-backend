"""Read and write .xlsx workbooks for the inventory ledger.

Products are never matched by name. Callers match `product_id`, `variant_id`,
or `sku` only. A workbook is rejected unless it is a real .xlsx file within
the size and row caps.
"""

import hashlib
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.core.exceptions import UnprocessableError
from app.models.inventory import ImportKind

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 2000
MAX_EXPORT_ROWS = 20_000
_XLSX_PREFIX = b"PK\x03\x04"
_FORMULA = ("=", "+", "-", "@")

PURCHASE_COLUMNS = (
    "supplier_name",
    "supplier_phone",
    "supplier_address",
    "supplier_note",
    "invoice_no",
    "purchased_on",
    "product_id",
    "sku",
    "variant_id",
    "quantity",
    "unit_cost",
)
OPENING_COLUMNS = ("product_id", "sku", "variant_id", "quantity")
STOCK_COUNT_COLUMNS = ("product_id", "sku", "variant_id", "counted_qty", "reason")
COST_COLUMNS = ("product_id", "sku", "variant_id", "unit_cost")

TEMPLATE_COLUMNS: dict[str, tuple[str, ...]] = {
    ImportKind.PURCHASES.value: PURCHASE_COLUMNS,
    ImportKind.OPENING.value: OPENING_COLUMNS,
    ImportKind.STOCK_COUNT.value: STOCK_COUNT_COLUMNS,
    ImportKind.COST_PRICE.value: COST_COLUMNS,
}

PRODUCT_EXPORT_COLUMNS = (
    "product_id",
    "variant_id",
    "sku",
    "title",
    "quantity",
    "cost_price",
    "status",
    "updated_at",
)
PURCHASE_EXPORT_COLUMNS = (
    "purchase_id",
    "purchased_on",
    "invoice_no",
    "supplier_name",
    "product_id",
    "variant_id",
    "sku",
    "quantity",
    "unit_cost",
)
MOVEMENT_EXPORT_COLUMNS = (
    "id",
    "created_at",
    "movement_type",
    "product_id",
    "variant_id",
    "sku",
    "quantity",
    "unit_cost",
    "order_id",
    "purchase_id",
    "import_batch_id",
    "actor_id",
    "note",
)


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def template_bytes(kind: str) -> bytes:
    columns = TEMPLATE_COLUMNS.get(kind)
    if columns is None:
        raise UnprocessableError("Unknown import template")
    return workbook_bytes(list(columns), [], kind.replace("_", " "))


def workbook_bytes(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    sheet_name: str,
    preamble: Sequence[Sequence[object]] | None = None,
) -> bytes:
    """Write a sheet. `preamble` rows (filter, dates) sit above the header.

    Money values stay numbers: pass `int`, `float`, or `Decimal`, not a taka string.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = sheet_name[:31] or "Sheet"
    for line in preamble or []:
        sheet.append([_export_cell(value) for value in line])
    sheet.append(list(headers))
    header_row = sheet.max_row
    for row in rows:
        sheet.append([_export_cell(value) for value in row])
    sheet.freeze_panes = f"A{header_row + 1}"
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def load_table(
    data: bytes, filename: str, required: tuple[str, ...]
) -> list[tuple[int, dict[str, object]]]:
    """Return `(excel_row_number, cells)` for each non-empty data row."""
    _reject_envelope(data, filename)
    try:
        book = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise UnprocessableError("This file is not a valid .xlsx workbook") from exc
    try:
        sheet = book.worksheets[0]
        grid = list(sheet.iter_rows(values_only=True))
    except Exception as exc:
        raise UnprocessableError("This file is not a valid .xlsx workbook") from exc
    finally:
        book.close()
    if len(grid) > 5001:
        raise UnprocessableError("The workbook has too many rows")
    if not grid:
        raise UnprocessableError("The workbook is empty")
    header = [_header(cell) for cell in grid[0]]
    names = [name for name in header if name]
    if not names:
        raise UnprocessableError("The first row must be the column names")
    if len(names) != len(set(names)):
        raise UnprocessableError("The workbook repeats a column name")
    missing = [name for name in required if name not in names]
    if missing:
        raise UnprocessableError("The workbook is missing a column: " + ", ".join(missing))
    index = {name: header.index(name) for name in names}
    parsed: list[tuple[int, dict[str, object]]] = []
    for offset, raw in enumerate(grid[1:], start=2):
        if _blank(raw):
            continue
        cells = {
            name: raw[position] if position < len(raw) else None for name, position in index.items()
        }
        parsed.append((offset, cells))
        if len(parsed) > MAX_IMPORT_ROWS:
            raise UnprocessableError("A workbook can contain at most 2000 data rows")
    return parsed


def _reject_envelope(data: bytes, filename: str) -> None:
    name = filename.strip().lower()
    if not name.endswith(".xlsx"):
        raise UnprocessableError("Upload an .xlsx workbook")
    if len(data) > MAX_IMPORT_BYTES:
        raise UnprocessableError("The workbook is larger than 2 MB")
    if not data.startswith(_XLSX_PREFIX):
        raise UnprocessableError("This file is not a valid .xlsx workbook")


def _header(value: object) -> str:
    return cell_str(value).lower().replace(" ", "_")


def _blank(row: tuple[object, ...] | list[object]) -> bool:
    return all(cell_str(cell) == "" for cell in row)


def cell_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def cell_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = cell_str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def cell_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value)
    text = cell_str(value).replace(",", "")
    if not text:
        return None
    sign = text[1:] if text.startswith("-") else text
    if not sign.isdigit():
        return None
    return int(text)


def cell_money(value: object) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount


def _export_cell(value: object) -> object:
    if isinstance(value, str) and value[:1] in _FORMULA:
        return "'" + value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
