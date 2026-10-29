"""Tabular exports: one call turns report rows into CSV, Excel or PDF with the same columns and totals as the
screen. CSV stays formula-injection safe (see csv_export)."""

import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi.responses import Response

from app.core.csv_export import csv_response

ExportFormat = Literal["csv", "xlsx", "pdf"]
Format = Literal["json", "csv", "xlsx", "pdf"]

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attachment(filename: str, content: bytes, media_type: str) -> Response:
    return Response(
        content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _xlsx(title: str, header: Sequence[str], rows: list[Sequence[Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "Report"
    ws.append(list(header))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        out = []
        for v in row:
            if isinstance(v, Decimal):
                out.append(float(v))  # spreadsheet cells are binary floats; the CSV keeps exact decimals
            elif v is None or isinstance(v, (int, float, str, date, datetime)):
                out.append(v)
            else:
                out.append(str(v))
        ws.append(out)
    for i, name in enumerate(header, start=1):
        width = max(
            [len(str(name))] + [len(str(r[i - 1])) for r in rows[:200] if i - 1 < len(r) and r[i - 1] is not None]
        )
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 60)
        if any(isinstance(r[i - 1], Decimal) for r in rows[:50] if i - 1 < len(r)):
            for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                cell.number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return f"{v:,.2f}"
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _pdf(title: str, header: Sequence[str], rows: list[Sequence[Any]]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    page = landscape(A4) if len(header) > 6 else A4
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7.5, leading=9)
    data = [[Paragraph(f"<b>{h}</b>", small) for h in header]]
    numeric = [any(isinstance(r[i], Decimal) for r in rows if i < len(r)) for i in range(len(header))]
    for r in rows:
        data.append([Paragraph(_cell_text(v).replace("&", "&amp;").replace("<", "&lt;"), small) for v in r])
    table = Table(data, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    style += [("ALIGN", (i, 1), (i, -1), "RIGHT") for i, n in enumerate(numeric) if n]
    table.setStyle(TableStyle(style))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc.build([Paragraph(title, styles["Heading2"]), Paragraph(f"Generated {stamp}", small), Spacer(1, 4 * mm), table])
    return buf.getvalue()


def export_response(
    format: ExportFormat, name: str, header: Sequence[str], rows: Iterable[Sequence[Any]], *, title: str | None = None
) -> Response:
    """`name` without extension, e.g. "trial-balance_2026-01-01_2026-12-31"."""
    if format == "csv":
        return csv_response(f"{name}.csv", header, rows)
    materialized = [list(r) for r in rows]
    label = title or name.replace("-", " ").replace("_", " ").capitalize()
    if format == "xlsx":
        return _attachment(f"{name}.xlsx", _xlsx(label, header, materialized), XLSX)
    return _attachment(f"{name}.pdf", _pdf(label, header, materialized), "application/pdf")
