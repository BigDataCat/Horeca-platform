"""Parse a CSV export from any POS into canonical sales.

One row per sale line. Required columns: ``sale_id``, ``occurred_at``, ``product_name``,
``quantity``, ``unit_price``. Optional: ``currency``, ``external_product_id``, ``uom``,
``net_value``, ``tax_value``. ``,`` and ``;`` delimiters are detected; with ``;`` a decimal
comma ("10,50") is accepted. The file is all-or-nothing: any invalid row rejects it.
"""

import csv
import io
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.schemas.sales import CanonicalSale, CanonicalSaleLine

REQUIRED_COLUMNS = {"sale_id", "occurred_at", "product_name", "quantity", "unit_price"}
MAX_ROWS = 20000


class CSVImportError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _decimal(value: str, decimal_comma: bool) -> Decimal:
    value = value.strip()
    if decimal_comma:
        value = value.replace(",", ".")
    return Decimal(value)


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_csv_sales(text: str, default_currency: str) -> list[CanonicalSale]:
    text = text.lstrip("﻿")
    if not text.strip():
        raise CSVImportError(["The file is empty"])

    header_line = text.splitlines()[0]
    delimiter = ";" if header_line.count(";") > header_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise CSVImportError([f"Missing required columns: {', '.join(sorted(missing))}"])

    decimal_comma = delimiter == ";"
    errors: list[str] = []
    sales: "OrderedDict[str, dict]" = OrderedDict()

    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            raise CSVImportError([f"Too many rows (maximum {MAX_ROWS})"])
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        try:
            sale_id = row["sale_id"]
            if not sale_id:
                raise ValueError("sale_id is empty")
            quantity = _decimal(row["quantity"], decimal_comma)
            unit_price = _decimal(row["unit_price"], decimal_comma)
            net = _decimal(row["net_value"], decimal_comma) if row.get("net_value") else quantity * unit_price
            tax = _decimal(row["tax_value"], decimal_comma) if row.get("tax_value") else Decimal("0")
            occurred_at = _datetime(row["occurred_at"])
            line = CanonicalSaleLine(
                external_product_id=row.get("external_product_id") or None,
                product_name=row["product_name"],
                quantity=quantity,
                uom=row.get("uom") or "EA",
                unit_price=unit_price,
                net_value=net,
                tax_value=tax,
            )
            currency = (row.get("currency") or default_currency).upper()
            sale = sales.setdefault(sale_id, {"occurred_at": occurred_at, "currency": currency, "lines": []})
            if sale["occurred_at"] != occurred_at:
                raise ValueError(f"sale {sale_id} has different occurred_at values")
            if sale["currency"] != currency:
                raise ValueError(f"sale {sale_id} has different currencies")
            sale["lines"].append(line)
        except (InvalidOperation, ValueError, ValidationError) as exc:
            errors.append(f"Row {number}: {exc if not isinstance(exc, InvalidOperation) else 'invalid number'}")
        if len(errors) >= 20:
            errors.append("Too many errors; stopped checking")
            break

    if errors:
        raise CSVImportError(errors)
    if not sales:
        raise CSVImportError(["The file contains no data rows"])

    result = []
    for sale_id, data in sales.items():
        net = sum((l.net_value for l in data["lines"]), Decimal("0"))
        tax = sum((l.tax_value for l in data["lines"]), Decimal("0"))
        result.append(
            CanonicalSale(
                external_id=sale_id,
                occurred_at=data["occurred_at"],
                currency=data["currency"],
                net_value=net,
                tax_value=tax,
                gross_value=net + tax,
                lines=data["lines"],
            )
        )
    return result
