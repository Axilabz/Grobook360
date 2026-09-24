"""Excel (.xlsx) generation for the Global Export Framework.

Financial/numeric columns are written as REAL Excel numeric cells with a
number_format applied (never a formatted string like "₹1,250.50") so
totals/recalculation work correctly for the user in Excel — see §10 of
the source prompt's own explicit "avoid ₹1,250.50 as plain string"
instruction.
"""

import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.export.columns import ExportColumn, to_decimal

_HEADER_FILL = PatternFill(start_color="0066FF", end_color="0066FF", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_TITLE_FONT = Font(bold=True, size=14)
_META_FONT = Font(italic=True, size=9, color="666666")

_NUMBER_FORMATS: dict[str, str] = {
    "currency": '#,##0.00',
    "number": '#,##0.##',
    "percent": '0.00"%"',
}


def _cell_value(col: ExportColumn, raw: Any) -> Any:
    if raw is None:
        return None
    if col.type in ("currency", "number", "percent"):
        d = to_decimal(raw)
        return float(d) if d is not None else None
    if col.type == "date":
        if isinstance(raw, (date, datetime)):
            return raw
        return str(raw)
    if col.type == "datetime":
        if isinstance(raw, (date, datetime)):
            return raw
        return str(raw)
    if col.type == "boolean":
        return bool(raw)
    return str(raw)


def generate_excel(
    *,
    title: str,
    tenant_name: str,
    generated_by: str,
    generated_at: datetime,
    applied_filters: dict[str, Any],
    columns: list[ExportColumn],
    rows: list[dict[str, Any]],
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "Export"

    row_cursor = 1
    ws.cell(row=row_cursor, column=1, value=title).font = _TITLE_FONT
    row_cursor += 1
    ws.cell(row=row_cursor, column=1, value=f"Business: {tenant_name}").font = _META_FONT
    row_cursor += 1
    ws.cell(row=row_cursor, column=1, value=f"Generated: {generated_at.strftime('%d-%b-%Y %H:%M')} by {generated_by}").font = _META_FONT
    row_cursor += 1
    if applied_filters:
        filter_text = "Filters: " + ", ".join(f"{k}={v}" for k, v in applied_filters.items() if v not in (None, ""))
        if filter_text != "Filters: ":
            ws.cell(row=row_cursor, column=1, value=filter_text).font = _META_FONT
            row_cursor += 1
    ws.cell(row=row_cursor, column=1, value=f"Records: {len(rows)}").font = _META_FONT
    row_cursor += 2

    header_row = row_cursor
    for idx, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=idx, value=col.header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(idx)].width = col.width

    for r, row in enumerate(rows, start=header_row + 1):
        for idx, col in enumerate(columns, start=1):
            raw = col.extractor(row)
            value = _cell_value(col, raw)
            cell = ws.cell(row=r, column=idx, value=value)
            if col.type in _NUMBER_FORMATS and value is not None:
                cell.number_format = _NUMBER_FORMATS[col.type]
            if col.type in ("currency", "number", "percent"):
                cell.alignment = Alignment(horizontal="right")

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
