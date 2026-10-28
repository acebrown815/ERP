import csv
import io
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from fastapi.responses import Response


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    text = str(value)
    # Neutralize spreadsheet formula injection (cells starting with = + - @).
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") and not _is_number(text) else text


def _is_number(text: str) -> bool:
    try:
        Decimal(text)
        return True
    except ArithmeticError:
        return False


def csv_response(filename: str, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return Response(
        content="﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
