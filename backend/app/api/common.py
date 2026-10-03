import csv
import io
from collections.abc import Iterable
from decimal import Decimal

from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 1000


def clamp_page(limit: int, offset: int, default_max: int = MAX_PAGE_SIZE) -> tuple[int, int]:
    return min(max(limit, 1), default_max), max(offset, 0)


def set_total(response: Response, db: Session, query) -> None:
    """Expose the unpaginated row count in the X-Total-Count header."""
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)


def _safe_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    text = str(value)
    # Neutralise spreadsheet formula injection.
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


def csv_response(filename: str, header: list[str], rows: Iterable[Iterable]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe_cell(cell) for cell in row])
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
