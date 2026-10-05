"""Turn supplier invoices into goods receipts: extract -> match -> reconcile -> review/auto-post."""

import hashlib
from datetime import datetime, time, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import InvoiceImport, ProductAlias
from app.models.location import Location
from app.models.product import Product
from app.models.purchasing import Supplier
from app.schemas.invoices import ExtractedInvoice
from app.schemas.purchasing import GoodsReceiptCreate, ReceiptLineCreate
from app.services.invoice_parsing import (
    MAX_FILE_BYTES,
    InvoiceReadError,
    detect_kind,
    normalize_key,
    normalize_tax_id,
    normalize_unit,
    parse_ubl,
    unwrap_zip,
)
from app.services.receipts import post_goods_receipt
from app.services.sales_ingestion import normalize_quantity

OPEN_STATUSES = ("draft",)
TOLERANCE_PER_LINE = Decimal("0.02")


class DuplicateInvoice(Exception):
    def __init__(self, existing: InvoiceImport) -> None:
        super().__init__("This file was already imported")
        self.existing = existing


def _dec(value) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


# ---------------------------------------------------------------- matching
def find_supplier(db: Session, company_id: int, name: str | None, tax_id: str | None) -> Supplier | None:
    suppliers = db.scalars(select(Supplier).where(Supplier.company_id == company_id, Supplier.active.is_(True))).all()
    wanted_tax = normalize_tax_id(tax_id)
    if wanted_tax:
        for supplier in suppliers:
            if normalize_tax_id(supplier.tax_identifier) == wanted_tax:
                return supplier
    if name:
        key = normalize_key(name)
        for supplier in suppliers:
            if normalize_key(supplier.name) == key:
                return supplier
    return None


def match_product(db: Session, company_id: int, supplier_id: int | None, line: dict) -> tuple[int | None, str | None]:
    """Resolve an invoice line to a product: remembered alias, then supplier SKU, then exact name."""
    key = normalize_key(line["description"])
    if key:
        for scope in ([ProductAlias.supplier_id == supplier_id] if supplier_id else []) + [ProductAlias.supplier_id.is_(None)]:
            alias = db.scalar(select(ProductAlias).where(ProductAlias.company_id == company_id, ProductAlias.alias_key == key, scope))
            if alias is not None:
                return alias.product_id, "alias"
    code = line.get("product_code")
    if code:
        product = db.scalar(select(Product).where(Product.company_id == company_id, Product.active.is_(True), func.lower(Product.sku) == code.lower()))
        if product is not None:
            return product.id, "sku"
    if key:
        for product in db.scalars(select(Product).where(Product.company_id == company_id, Product.active.is_(True))).all():
            if normalize_key(product.name) == key:
                return product.id, "name"
    return None, None


def check_conversion(db: Session, company_id: int, product_id: int, unit: str | None, quantity: Decimal) -> bool:
    product = db.get(Product, product_id)
    if product is None:
        return False
    _, resulting = normalize_quantity(db, company_id, product, quantity or Decimal(1), unit or product.base_uom)
    return resulting == product.base_uom.upper()


# ---------------------------------------------------------------- draft building
def reconcile(extracted: dict) -> list[str]:
    """Warnings when the numbers on the invoice do not add up (never blocks silently: a person decides)."""
    warnings: list[str] = []
    lines = extracted["lines"]
    nets = [_dec(l.get("line_net")) for l in lines]
    if all(n is not None for n in nets) and lines:
        total_lines = sum(nets, Decimal(0))
        header = _dec(extracted["header"].get("total_net"))
        if header is not None and abs(total_lines - header) > TOLERANCE_PER_LINE * len(lines):
            warnings.append(f"Lines add up to {total_lines} but the invoice net total is {header}")
    net, vat, gross = (_dec(extracted["header"].get(k)) for k in ("total_net", "total_vat", "total_gross"))
    if None not in (net, vat, gross) and abs(net + vat - gross) > Decimal("0.05"):
        warnings.append(f"Net {net} + VAT {vat} does not equal gross {gross}")
    for index, line in enumerate(lines):
        qty, price, net_line = _dec(line.get("quantity")), _dec(line.get("unit_price")), _dec(line.get("line_net"))
        if qty and price is not None and net_line is not None and abs(qty * price - net_line) > Decimal("0.05") + TOLERANCE_PER_LINE:
            warnings.append(f"Line {index + 1}: {qty} x {price} is not {net_line}")
        if price is None and (net_line is None or not qty):
            warnings.append(f"Line {index + 1} has no price")
    return warnings


def _line_dict(line, product_id, how) -> dict:
    return {
        "description": line.description,
        "product_code": line.product_code,
        "quantity": _money(line.quantity),
        "unit": line.unit,
        "unit_price": _money(line.unit_price),
        "line_net": _money(line.line_net),
        "vat_rate": _money(line.vat_rate),
        "product_id": product_id,
        "match": how,
        "skip": False,
    }


def build_draft(db: Session, inv: InvoiceImport, invoice: ExtractedInvoice) -> None:
    """Fill ``inv.extracted``/``warnings``/``supplier_id`` from an extracted invoice."""
    supplier = find_supplier(db, inv.company_id, invoice.supplier_name, invoice.supplier_tax_id)
    inv.supplier_id = supplier.id if supplier else None
    lines = []
    for line in invoice.lines:
        draft = _line_dict(line, None, None)
        draft["product_id"], draft["match"] = match_product(db, inv.company_id, inv.supplier_id, draft)
        lines.append(draft)
    inv.extracted = {
        "header": {
            "document_type": invoice.document_type,
            "supplier_name": invoice.supplier_name,
            "supplier_tax_id": invoice.supplier_tax_id,
            "document_number": invoice.document_number,
            "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
            "currency": invoice.currency,
            "total_net": _money(invoice.total_net),
            "total_vat": _money(invoice.total_vat),
            "total_gross": _money(invoice.total_gross),
        },
        "lines": lines,
    }
    warnings = reconcile(inv.extracted)
    if supplier is None and invoice.supplier_name:
        warnings.append(f"New supplier '{invoice.supplier_name}' will be created when the receipt is posted")
    if supplier and invoice.document_number:
        duplicate = db.scalar(
            select(func.count(InvoiceImport.id)).where(
                InvoiceImport.company_id == inv.company_id,
                InvoiceImport.supplier_id == supplier.id,
                InvoiceImport.status == "posted",
                InvoiceImport.extracted["header"]["document_number"].as_string() == invoice.document_number,
            )
        )
        if duplicate:
            warnings.append(f"Invoice {invoice.document_number} from {supplier.name} was already posted")
    inv.warnings = warnings
    refresh_conversions(db, inv)


def refresh_conversions(db: Session, inv: InvoiceImport) -> None:
    for line in inv.extracted["lines"]:
        line["conversion_ok"] = (
            check_conversion(db, inv.company_id, line["product_id"], line.get("unit"), _dec(line.get("quantity")) or Decimal(1))
            if line.get("product_id")
            else None
        )


def blocking_issues(db: Session, inv: InvoiceImport) -> list[str]:
    """Why this draft cannot be posted yet (empty list = ready)."""
    if inv.status != "draft" or not inv.extracted:
        return []
    issues: list[str] = []
    header = inv.extracted["header"]
    if header.get("document_type") == "credit_note":
        issues.append("Credit notes are not supported: reject this document and record the return manually")
    if inv.location_id is None:
        issues.append("Choose the receiving location")
    active = [l for l in inv.extracted["lines"] if not l.get("skip")]
    if not active:
        issues.append("The invoice has no lines to receive")
    for index, line in enumerate(inv.extracted["lines"], start=1):
        if line.get("skip"):
            continue
        if not line.get("product_id"):
            issues.append(f"Line {index} ({line['description']}) is not matched to a product")
        elif not check_conversion(db, inv.company_id, line["product_id"], line.get("unit"), _dec(line.get("quantity")) or Decimal(1)):
            issues.append(f"Line {index}: no unit conversion from {line.get('unit') or '?'} to the product's base unit")
        cost = _unit_cost(line)
        if cost is None or cost <= 0:
            issues.append(f"Line {index} has no usable price (a discount or free item: skip it)")
    return issues


def _unit_cost(line: dict) -> Decimal | None:
    price = _dec(line.get("unit_price"))
    if price is not None:
        return price
    net, qty = _dec(line.get("line_net")), _dec(line.get("quantity"))
    return net / qty if net is not None and qty else None


def default_location(db: Session, company: Company) -> int | None:
    if company.invoice_default_location_id:
        location = db.get(Location, company.invoice_default_location_id)
        if location and location.company_id == company.id and location.active:
            return location.id
    active = db.scalars(select(Location).where(Location.company_id == company.id, Location.active.is_(True))).all()
    return active[0].id if len(active) == 1 else None


# ---------------------------------------------------------------- import
def import_invoice(
    db: Session,
    company: Company,
    user_id: int | None,
    content: bytes,
    filename: str | None,
    content_type: str | None,
    source: str = "upload",
    location_id: int | None = None,
    mail_message_id: str | None = None,
) -> InvoiceImport:
    """Read a file into a draft invoice. Raises ``DuplicateInvoice`` if the same file was imported before.

    A file that cannot be read is stored with status ``failed`` and the reason, so it stays visible."""
    if not content:
        raise InvoiceReadError("The file is empty")
    if len(content) > MAX_FILE_BYTES:
        raise InvoiceReadError("The file is too large (10 MB maximum)")
    sha = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(InvoiceImport).where(InvoiceImport.company_id == company.id, InvoiceImport.content_sha256 == sha))
    if existing is not None:
        raise DuplicateInvoice(existing)

    kind = detect_kind(content)
    inv = InvoiceImport(
        company_id=company.id,
        location_id=location_id or default_location(db, company),
        source=source,
        source_type=kind,
        filename=(filename or "")[:300] or None,
        content_sha256=sha,
        content_type=(content_type or "")[:100] or None,
        content=content,
        status="draft",
        mail_message_id=mail_message_id,
        created_by_id=user_id,
    )
    db.add(inv)
    try:
        if kind == "ubl_xml":
            xml = unwrap_zip(content) if content.startswith(b"PK") else content
            invoice = parse_ubl(xml)
        else:
            from app.services.invoice_ai import extract_with_ai  # imported lazily: needs the anthropic SDK

            invoice = extract_with_ai(content, kind)
        if not invoice.lines:
            raise InvoiceReadError("No invoice lines were found in the document")
        build_draft(db, inv, invoice)
    except InvoiceReadError as exc:
        inv.status = "failed"
        inv.error = str(exc)
    db.commit()  # the draft is saved before anything else is attempted
    db.refresh(inv)

    if inv.status == "draft" and kind == "ubl_xml" and company.invoice_auto_post:
        _try_auto_post(db, inv, user_id)
        db.refresh(inv)
    return inv


def _try_auto_post(db: Session, inv: InvoiceImport, user_id: int | None) -> None:
    """Auto-post only structured (XML) invoices that matched completely and reconcile exactly."""
    if blocking_issues(db, inv) or any(w for w in (inv.warnings or []) if not w.startswith("New supplier")):
        return
    inv_id = inv.id
    try:
        post_invoice(db, inv, user_id)
    except HTTPException as exc:
        db.rollback()
        draft = db.get(InvoiceImport, inv_id)
        draft.warnings = list(draft.warnings or []) + [f"Automatic posting failed: {exc.detail}"]
        db.commit()


def _received_at(issue_date: str | None) -> datetime | None:
    if not issue_date:
        return None
    moment = datetime.combine(datetime.fromisoformat(issue_date).date(), time(12, 0), tzinfo=timezone.utc)
    return min(moment, datetime.now(timezone.utc))


def post_invoice(db: Session, inv: InvoiceImport, user_id: int | None, location_id: int | None = None) -> InvoiceImport:
    if inv.status != "draft":
        raise HTTPException(status_code=409, detail=f"Invoice is already {inv.status}")
    if location_id:
        inv.location_id = location_id
    issues = blocking_issues(db, inv)
    if issues:
        raise HTTPException(status_code=400, detail="; ".join(issues))

    header = inv.extracted["header"]
    supplier_id = inv.supplier_id
    if supplier_id is None and header.get("supplier_name"):
        supplier = Supplier(company_id=inv.company_id, name=header["supplier_name"][:200], tax_identifier=(header.get("supplier_tax_id") or None))
        supplier_existing = db.scalar(select(Supplier).where(Supplier.company_id == inv.company_id, Supplier.name == supplier.name))
        if supplier_existing is None:
            db.add(supplier)
            db.flush()
            supplier_existing = supplier
        supplier_id = supplier_existing.id
        inv.supplier_id = supplier_id

    active = [l for l in inv.extracted["lines"] if not l.get("skip")]
    payload = GoodsReceiptCreate(
        location_id=inv.location_id,
        supplier_id=supplier_id,
        document_number=header.get("document_number"),
        received_at=_received_at(header.get("issue_date")),
        currency=header.get("currency"),
        note=f"Imported from invoice file {inv.filename or inv.id}",
        lines=[
            ReceiptLineCreate(
                product_id=l["product_id"],
                quantity=_dec(l["quantity"]),
                uom=l.get("unit") or db.get(Product, l["product_id"]).base_uom,
                unit_cost=_unit_cost(l),
            )
            for l in active
        ],
    )
    receipt = post_goods_receipt(db, inv.company_id, user_id, payload)
    inv.receipt_id = receipt.id
    inv.status = "posted"
    inv.posted_at = datetime.now(timezone.utc)
    learn_aliases(db, inv, active)
    db.commit()
    db.refresh(inv)
    return inv


def learn_aliases(db: Session, inv: InvoiceImport, lines: list[dict]) -> None:
    """Remember supplier wording for every matched line so the next invoice needs no review."""
    for line in lines:
        key = normalize_key(line["description"])
        if not key or not line.get("product_id"):
            continue
        scope = ProductAlias.supplier_id == inv.supplier_id if inv.supplier_id else ProductAlias.supplier_id.is_(None)
        alias = db.scalar(select(ProductAlias).where(ProductAlias.company_id == inv.company_id, ProductAlias.alias_key == key, scope))
        if alias is None:
            db.add(ProductAlias(company_id=inv.company_id, supplier_id=inv.supplier_id, alias_key=key, product_id=line["product_id"]))
        else:
            alias.product_id = line["product_id"]


def apply_patch(db: Session, inv: InvoiceImport, patch, company_id: int) -> None:
    """Apply a person's corrections to a draft."""
    if inv.status != "draft":
        raise HTTPException(status_code=409, detail=f"Invoice is already {inv.status}")
    data = dict(inv.extracted)  # copy so SQLAlchemy sees the JSON change
    data["header"] = dict(data["header"])
    data["lines"] = [dict(l) for l in data["lines"]]
    if patch.location_id is not None:
        location = db.get(Location, patch.location_id)
        if location is None or location.company_id != company_id:
            raise HTTPException(status_code=404, detail="Location not found")
        inv.location_id = location.id
    if patch.supplier_id is not None:
        supplier = db.get(Supplier, patch.supplier_id)
        if supplier is None or supplier.company_id != company_id:
            raise HTTPException(status_code=404, detail="Supplier not found")
        inv.supplier_id = supplier.id
    if patch.document_number is not None:
        data["header"]["document_number"] = patch.document_number or None
    if patch.issue_date is not None:
        data["header"]["issue_date"] = patch.issue_date.isoformat()
    for change in patch.lines:
        if change.index >= len(data["lines"]):
            raise HTTPException(status_code=400, detail=f"There is no line {change.index + 1}")
        line = data["lines"][change.index]
        if change.clear_product:
            line["product_id"], line["match"] = None, None
        if change.product_id is not None:
            product = db.get(Product, change.product_id)
            if product is None or product.company_id != company_id:
                raise HTTPException(status_code=404, detail="Product not found")
            line["product_id"], line["match"] = product.id, "manual"
        if change.skip is not None:
            line["skip"] = change.skip
        if change.quantity is not None:
            line["quantity"] = _money(change.quantity)
        if change.unit is not None:
            line["unit"] = normalize_unit(change.unit)
        if change.unit_price is not None:
            line["unit_price"] = _money(change.unit_price)
    inv.extracted = data
    refresh_conversions(db, inv)
    inv.warnings = reconcile(inv.extracted) + [w for w in (inv.warnings or []) if w.startswith(("New supplier", "Invoice "))]
