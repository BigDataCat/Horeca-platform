"""Read supplier invoices: e-Factura UBL XML (deterministic) and, in invoice_ai.py, PDF/photos (AI)."""

import io
import re
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree as SafeET

from app.schemas.invoices import ExtractedInvoice, ExtractedLine

MAX_FILE_BYTES = 10 * 1024 * 1024

# UN/ECE Recommendation 20 codes used by e-Factura, plus the abbreviations found on Romanian invoices.
UNIT_MAP = {
    "H87": "EA", "C62": "EA", "EA": "EA", "PCE": "EA", "NIU": "EA", "BUC": "EA", "BUCATA": "EA", "BUCATI": "EA", "PC": "EA", "PCS": "EA",
    "KGM": "KG", "KG": "KG", "KILOGRAM": "KG", "KILOGRAME": "KG",
    "GRM": "G", "G": "G", "GR": "G", "GRAM": "G", "GRAME": "G",
    "LTR": "L", "L": "L", "LT": "L", "LITRU": "L", "LITRI": "L",
    "MLT": "ML", "ML": "ML", "CLT": "CL", "CL": "CL",
    "MTR": "M", "M": "M", "XBX": "BOX", "BOX": "BOX", "CUTIE": "BOX", "CTN": "BOX",
    "XBO": "BOTTLE", "XPK": "PACK", "PK": "PACK", "PACHET": "PACK", "SET": "SET", "BAX": "CASE", "CASE": "CASE",
}


def normalize_unit(raw: str | None) -> str | None:
    if not raw:
        return None
    code = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    return UNIT_MAP.get(code, code or None)


def normalize_key(text: str) -> str:
    """Lower-case, strip diacritics and punctuation: 'Roșii  cherry, 500g' -> 'rosii cherry 500g'."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def normalize_tax_id(raw: str | None) -> str | None:
    """'RO 12345678' / 'RO12345678' / '12345678' -> '12345678'."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits or None


class InvoiceReadError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(element, *path: str):
    """First descendant following the local-name path, ignoring namespaces."""
    current = [element]
    for name in path:
        nxt = []
        for node in current:
            nxt.extend(child for child in node if _local(child.tag) == name)
        if not nxt:
            return None
        current = nxt
    return current[0]


def _findall(element, name: str):
    return [child for child in element if _local(child.tag) == name]


def _text(element, *path: str) -> str | None:
    node = _find(element, *path) if path else element
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        raise InvoiceReadError(f"Invalid number in the invoice: {value!r}")


def unwrap_zip(content: bytes) -> bytes:
    """e-Factura downloads are ZIP files holding the invoice XML next to a signature file."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise InvoiceReadError("The ZIP file is damaged")
    members = [i for i in archive.infolist() if i.filename.lower().endswith(".xml") and not i.is_dir()]
    members = [m for m in members if "semnatura" not in m.filename.lower() and "signature" not in m.filename.lower()] or members
    if not members:
        raise InvoiceReadError("The ZIP file contains no XML invoice")
    member = max(members, key=lambda m: m.file_size)
    if member.file_size > MAX_FILE_BYTES:
        raise InvoiceReadError("The XML inside the ZIP is too large")
    return archive.read(member)


def parse_ubl(content: bytes) -> ExtractedInvoice:
    """Parse a UBL 2.1 Invoice or CreditNote (RO e-Factura / CIUS-RO)."""
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:  # malformed or hostile XML (entity expansion etc. is rejected by defusedxml)
        raise InvoiceReadError(f"Not a readable XML invoice: {exc.__class__.__name__}")

    kind = _local(root.tag)
    if kind not in {"Invoice", "CreditNote"}:
        raise InvoiceReadError("The XML is not a UBL Invoice or CreditNote")
    line_tag = "InvoiceLine" if kind == "Invoice" else "CreditNoteLine"
    qty_tag = "InvoicedQuantity" if kind == "Invoice" else "CreditedQuantity"

    party = _find(root, "AccountingSupplierParty", "Party")
    supplier_name = tax_id = None
    if party is not None:
        supplier_name = _text(party, "PartyLegalEntity", "RegistrationName") or _text(party, "PartyName", "Name")
        tax_id = _text(party, "PartyTaxScheme", "CompanyID") or _text(party, "PartyLegalEntity", "CompanyID")

    issue = _text(root, "IssueDate")
    lines: list[ExtractedLine] = []
    for node in _findall(root, line_tag):
        quantity_node = _find(node, qty_tag)
        quantity = _decimal(quantity_node.text) if quantity_node is not None and quantity_node.text else None
        if quantity is None:
            raise InvoiceReadError("An invoice line has no quantity")
        price = _decimal(_text(node, "Price", "PriceAmount"))
        base_qty = _decimal(_text(node, "Price", "BaseQuantity"))
        if price is not None and base_qty and base_qty != 1:
            price = price / base_qty
        item = _find(node, "Item")
        description = (_text(item, "Name") if item is not None else None) or (_text(item, "Description") if item is not None else None)
        if not description:
            raise InvoiceReadError("An invoice line has no item name")
        code = _text(item, "SellersItemIdentification", "ID") if item is not None else None
        vat = _decimal(_text(item, "ClassifiedTaxCategory", "Percent")) if item is not None else None
        lines.append(
            ExtractedLine(
                description=description,
                product_code=code,
                quantity=quantity,
                unit=normalize_unit(quantity_node.attrib.get("unitCode")),
                unit_price=price,
                line_net=_decimal(_text(node, "LineExtensionAmount")),
                vat_rate=vat,
            )
        )

    totals = _find(root, "LegalMonetaryTotal")
    tax_total = _decimal(_text(root, "TaxTotal", "TaxAmount"))
    return ExtractedInvoice(
        document_type="credit_note" if kind == "CreditNote" else "invoice",
        supplier_name=supplier_name,
        supplier_tax_id=tax_id,
        document_number=_text(root, "ID"),
        issue_date=issue,
        currency=_text(root, "DocumentCurrencyCode"),
        lines=lines,
        total_net=_decimal(_text(totals, "TaxExclusiveAmount")) if totals is not None else None,
        total_vat=tax_total,
        total_gross=_decimal(_text(totals, "TaxInclusiveAmount")) if totals is not None else None,
    )


def detect_kind(content: bytes) -> str:
    """Decide how to read a file from its first bytes (never from the file name alone)."""
    head = content[:16]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or (head[:4] == b"RIFF" and content[8:12] == b"WEBP"):
        return "image"
    if head.startswith(b"PK"):
        return "ubl_xml"  # e-Factura ZIP
    if content.lstrip()[:1] == b"<":
        return "ubl_xml"
    raise InvoiceReadError("Unsupported file. Upload an e-Factura XML/ZIP, a PDF, or a PNG/JPEG/WEBP image.")


def image_media_type(content: bytes) -> str:
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "image/webp"
