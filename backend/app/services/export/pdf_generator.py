"""PDF generation for the Global Export Framework (reportlab).

Portrait vs landscape is chosen automatically from the number of
columns (§11 of the source prompt: "automatically select portrait or
landscape based on table width where possible") — a simple, deterministic
heuristic rather than exact text-width measurement, which is adequate
for tabular exports of this MVP's typical column counts. reportlab's
own `Table` with `repeatRows=1` handles repeated headers across pages
natively, and `LongTable`-style automatic pagination avoids clipped/
overlapping content by construction (cells wrap rather than overflow).
"""

import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.export.columns import ExportColumn, to_decimal

_LANDSCAPE_COLUMN_THRESHOLD = 6  # more columns than this -> landscape
_BRAND_BLUE = colors.HexColor("#0066FF")


def _format_cell(col: ExportColumn, raw: Any) -> str:
    if raw is None:
        return ""
    if col.type == "currency":
        d = to_decimal(raw)
        return f"{d:,.2f}" if d is not None else ""
    if col.type == "number":
        d = to_decimal(raw)
        return f"{d:,.2f}".rstrip("0").rstrip(".") if d is not None else ""
    if col.type == "percent":
        d = to_decimal(raw)
        return f"{d:.2f}%" if d is not None else ""
    if col.type in ("date", "datetime") and isinstance(raw, (date, datetime)):
        return raw.strftime("%d-%b-%Y") if col.type == "date" else raw.strftime("%d-%b-%Y %H:%M")
    if col.type == "boolean":
        return "Yes" if raw else "No"
    return str(raw)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def generate_pdf(
    *,
    title: str,
    tenant_name: str,
    generated_by: str,
    generated_at: datetime,
    applied_filters: dict[str, Any],
    columns: list[ExportColumn],
    rows: list[dict[str, Any]],
) -> bytes:
    orientation = landscape if len(columns) > _LANDSCAPE_COLUMN_THRESHOLD else portrait
    pagesize = orientation(A4)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=pagesize,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ExportTitle", parent=styles["Title"], fontSize=16, spaceAfter=4)
    meta_style = ParagraphStyle("ExportMeta", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10)
    header_style = ParagraphStyle("HeaderCell", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")

    story = [Paragraph(title, title_style), Paragraph(f"Business: {tenant_name}", meta_style)]
    story.append(Paragraph(f"Generated: {generated_at.strftime('%d-%b-%Y %H:%M')} by {generated_by}", meta_style))
    filter_parts = [f"{k}={v}" for k, v in applied_filters.items() if v not in (None, "")]
    if filter_parts:
        story.append(Paragraph("Filters: " + ", ".join(filter_parts), meta_style))
    story.append(Paragraph(f"Records: {len(rows)}", meta_style))
    story.append(Spacer(1, 6 * mm))

    if not rows:
        story.append(Paragraph("No records found for the selected filters.", styles["Normal"]))
    else:
        # Header row uses Paragraph cells too, so long headers wrap instead
        # of clipping — never a raw string that reportlab could overflow.
        table_data: list[list[Any]] = [[Paragraph(c.header, header_style) for c in columns]]
        numeric_col_indexes = {i for i, c in enumerate(columns) if c.type in ("currency", "number", "percent")}
        for row in rows:
            table_data.append([Paragraph(_format_cell(c, c.extractor(row)), cell_style) for c in columns])

        available_width = pagesize[0] - 30 * mm
        col_width = available_width / len(columns)
        table = Table(table_data, colWidths=[col_width] * len(columns), repeatRows=1)
        style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), _BRAND_BLUE),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
        ]
        for idx in numeric_col_indexes:
            style_commands.append(("ALIGN", (idx, 1), (idx, -1), "RIGHT"))
        table.setStyle(TableStyle(style_commands))
        story.append(table)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
