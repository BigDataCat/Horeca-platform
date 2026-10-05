"""Read PDF and photographed invoices on this server, without sending anything to a cloud service.

Pipeline: PDF text layer (pdfplumber) -> or OCR (Tesseract, Romanian + English) for scans and photos ->
rule-based parsing. A line is accepted only when quantity x unit price matches its total (or when a
table with recognised column headers gives it directly), so noise is dropped instead of invented.
Accuracy depends on the layout: the result is always shown to a person for review."""

import io
import re
import shutil
from datetime import date
from decimal import Decimal, InvalidOperation

from app.schemas.invoices import ExtractedInvoice, ExtractedLine
from app.services.invoice_parsing import InvoiceReadError, normalize_key, normalize_unit

MAX_PAGES = 6
OCR_LANGS = "ron+eng"

UNIT_WORDS = r"(?:buc|bucati|bucăți|kg|g|gr|l|lt|ml|cl|m|set|cutie|bax|pachet|pac|sticla|sticlă|borcan|punga|pungă|palet|ctn|pcs|pc)"
NUM = r"-?\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|-?\d+(?:[.,]\d+)?"

HEADER_WORDS = {
    "description": ("denumire", "produs", "articol", "descriere", "description", "item", "marfa", "mărfuri", "marfuri"),
    "unit": ("u.m", "um", "u/m", "unit", "unitate"),
    "quantity": ("cant", "qty", "quantity", "cantitate"),
    "price": ("pret", "preț", "pu", "p.u", "price", "unitar"),
    "net": ("valoare", "value", "amount", "total"),
    "vat": ("tva", "vat"),
    "code": ("cod", "code", "sku"),
}


def parse_number(raw: str | None) -> Decimal | None:
    """'1.234,56' -> 1234.56 · '1 234,5' -> 1234.5 · '12.50' -> 12.50 · '12,50' -> 12.50."""
    if raw is None:
        return None
    text = raw.strip().replace(" ", " ")
    if not text or not re.search(r"\d", text):
        return None
    text = re.sub(r"[^\d,.\-\s]", "", text).strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(" ", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "").replace(" ", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = head.replace(" ", "").replace(",", "") + "." + tail if len(tail) != 3 or " " in head or head.count(",") else text.replace(",", ".").replace(" ", "")
    else:
        text = text.replace(" ", "")
        if text.count(".") > 1:
            text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def number_variants(raw: str) -> list[Decimal]:
    """Candidate values for a token: '1.000' / '3,000' can mean a thousand or one / three (decimals).
    The caller keeps whichever reading makes the line's arithmetic work."""
    primary = parse_number(raw)
    if primary is None:
        return []
    text = raw.strip()
    if re.fullmatch(r"-?\d{1,3}[.,]\d{3}", text):
        digits = text.replace(".", "").replace(",", "")
        thousand = Decimal(digits)
        decimal = Decimal(text.replace(",", "."))
        return [thousand, decimal] if thousand != decimal else [thousand]
    return [primary]


# ------------------------------------------------------------------ getting text
def _ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def remove_table_lines(gray, min_run: int = 60):
    """Erase long horizontal/vertical ruling lines: Tesseract otherwise skips the cells of ruled tables."""
    import numpy as np
    from PIL import Image

    pixels = np.array(gray)
    dark = pixels < 170

    def erase_runs(mask):
        out = mask.copy()
        for index in range(mask.shape[0]):
            row = mask[index]
            if row.sum() < min_run:
                continue
            padded = np.concatenate(([0], row.view(np.int8), [0]))
            edges = np.flatnonzero(np.diff(padded))
            for start, end in zip(edges[::2], edges[1::2]):
                if end - start >= min_run:
                    out[index, start:end] = False
        return out

    cleaned = erase_runs(erase_runs(dark).T).T  # rows, then columns
    result = np.where(cleaned, 0, 255).astype("uint8")
    return Image.fromarray(result)


def _score(text: str) -> int:
    return len(_lines_from_text(text))


def ocr_image(image) -> str:
    """OCR with a few preprocessing/page-segmentation variants; keeps the one that yields most invoice lines."""
    if not _ocr_available():
        raise InvoiceReadError("OCR is not installed on this server (Tesseract). Upload the e-Factura XML or a PDF with selectable text.")
    import pytesseract
    from PIL import Image, ImageOps

    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    if max(gray.size) < 3000:  # low-resolution scans/photos read badly: scale up (about 250 dpi on A4)
        factor = 3000 / max(gray.size)
        gray = gray.resize((int(gray.width * factor), int(gray.height * factor)), Image.LANCZOS)
    variants = [(remove_table_lines(gray), "--psm 6"), (gray, "--psm 6"), (remove_table_lines(gray), "--psm 4")]
    best_text, best_score = "", -1
    try:
        for candidate, config in variants:
            text = pytesseract.image_to_string(candidate, lang=OCR_LANGS, config=config)
            score = _score(text)
            if score > best_score or (score == best_score and len(text) > len(best_text)):
                best_text, best_score = text, score
            if score >= 3:
                break
    except pytesseract.TesseractError as exc:
        raise InvoiceReadError(f"OCR failed: {str(exc)[:120]}")
    return best_text


def pdf_text_and_tables(content: bytes) -> tuple[str, list[list[list[str | None]]]]:
    import pdfplumber

    texts: list[str] = []
    tables: list[list[list[str | None]]] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages[:MAX_PAGES]:
                texts.append(page.extract_text() or "")
                tables.extend(page.extract_tables() or [])
            text = "\n".join(texts)
            if len(re.sub(r"\s", "", text)) < 40:  # no text layer: a scan. Rasterise and OCR it.
                ocr_pages = [ocr_image(page.to_image(resolution=250).original) for page in pdf.pages[:MAX_PAGES]]
                return "\n".join(ocr_pages), []
            return text, tables
    except InvoiceReadError:
        raise
    except Exception as exc:
        raise InvoiceReadError(f"The PDF could not be read ({exc.__class__.__name__})")


def read_text(content: bytes, kind: str) -> tuple[str, list]:
    if kind == "pdf":
        return pdf_text_and_tables(content)
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception:
        raise InvoiceReadError("The image could not be opened")
    return ocr_image(image), []


# ------------------------------------------------------------------ parsing
def _column_map(header: list[str]) -> dict[str, int] | None:
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = normalize_key(cell or "")
        if not key:
            continue
        for field, words in HEADER_WORDS.items():
            if field in found:
                continue
            if any(key == normalize_key(w) or key.startswith(normalize_key(w)) for w in words):
                if field == "net" and "tva" in key and not re.search(r"fara|excl|net|without", key):
                    continue
                found[field] = index
    return found if {"description", "quantity"} <= found.keys() and ({"price", "net"} & found.keys()) else None


def _lines_from_tables(tables) -> list[ExtractedLine]:
    out: list[ExtractedLine] = []
    for table in tables:
        header_at = next((i for i, row in enumerate(table[:4]) if _column_map([c or "" for c in row])), None)
        if header_at is None:
            continue
        columns = _column_map([c or "" for c in table[header_at]])
        for row in table[header_at + 1:]:
            cells = [(c or "").replace("\n", " ").strip() for c in row]
            if len(cells) <= max(columns.values()):
                continue
            description = cells[columns["description"]]
            quantity = parse_number(cells[columns["quantity"]])
            if not description or quantity is None or quantity == 0 or re.match(r"(?i)^total", description):
                continue
            price = parse_number(cells[columns["price"]]) if "price" in columns else None
            net = parse_number(cells[columns["net"]]) if "net" in columns else None
            out.append(ExtractedLine(
                description=description,
                product_code=cells[columns["code"]] or None if "code" in columns else None,
                quantity=quantity,
                unit=normalize_unit(cells[columns["unit"]]) if "unit" in columns else None,
                unit_price=price,
                line_net=net,
                vat_rate=parse_number(cells[columns["vat"]]) if "vat" in columns and (parse_number(cells[columns["vat"]]) or 0) in (0, 5, 9, 11, 19, 21) else None,
            ))
    return out


_LINE = re.compile(rf"^\s*(?:\d{{1,3}}[.)]?\s+)?(?P<desc>.*?\S)\s+(?P<unit>{UNIT_WORDS})\.?\s+(?P<nums>(?:{NUM})(?:\s+(?:{NUM})){{1,4}})\s*$", re.I)
_NUM_RE = re.compile(NUM)
CENT = Decimal("0.05")


def _lines_from_text(text: str) -> list[ExtractedLine]:
    """Lines shaped 'name unit qty price value [vat]'. Accepted only if qty x price matches a value on the line."""
    out: list[ExtractedLine] = []
    for raw in text.splitlines():
        raw = re.sub(r"[|¦│_]+", " ", raw)  # leftovers of table borders read by OCR
        match = _LINE.match(raw)
        if not match:
            continue
        tokens = _NUM_RE.findall(match.group("nums"))
        variants = [number_variants(t) for t in tokens]
        if len(variants) < 2 or any(not v for v in variants):
            continue
        chosen = None
        for quantity in variants[0]:
            if quantity <= 0:
                continue
            for price_index in range(1, len(variants)):
                for price in variants[price_index]:
                    for later in variants[price_index + 1:]:
                        for value in later:
                            if abs(quantity * price - value) <= CENT + abs(value) * Decimal("0.005"):
                                chosen = (quantity, price, value)
                                break
                        if chosen:
                            break
                    if chosen:
                        break
                if chosen:
                    break
            if chosen:
                break
        if chosen is None:
            continue  # cannot verify the arithmetic: skip the line rather than guess
        description = match.group("desc").strip(" .|-")
        if not description or re.match(r"(?i)^(total|tva|subtotal)", description):
            continue
        out.append(ExtractedLine(description=description, quantity=chosen[0], unit=normalize_unit(match.group("unit")), unit_price=chosen[1], line_net=chosen[2]))
    return out


def _find(pattern: str, text: str, flags=re.I) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def _parse_date(text: str) -> date | None:
    for pattern, order in ((r"(\d{4})-(\d{2})-(\d{2})", "ymd"), (r"(\d{1,2})[./](\d{1,2})[./](\d{4})", "dmy")):
        for match in re.finditer(pattern, text):
            try:
                a, b, c = (int(x) for x in match.groups())
                return date(a, b, c) if order == "ymd" else date(c, b, a)
            except ValueError:
                continue
    return None


def _header(text: str) -> dict:
    head = text[:2500]
    supplier_block = re.split(r"(?i)\b(?:client|cump[aă]r[aă]tor|beneficiar|buyer|bill to)\b", head)[0]
    name = _find(r"(?:furnizor|vanz[aă]tor|vânz[aă]tor|seller|supplier)\s*[:\-]?\s*\n?\s*([^\n]{3,80})", supplier_block)
    if not name:
        name = next((l.strip() for l in supplier_block.splitlines() if re.search(r"\b(?:S\.?R\.?L|S\.?A|S\.?C\.?|PFA|II|SNC)\b", l, re.I)), None)
    tax = _find(r"(?:CUI|CIF|C\.I\.F|C\.U\.I|cod\s*fiscal|VAT(?:\s*ID)?)\s*[:.\-]?\s*((?:RO)?\s?\d{2,10})", supplier_block) or _find(r"\b(RO\s?\d{2,10})\b", supplier_block)
    number = _find(r"(?:factur[aă]|invoice|NIR|aviz)\b[^\n\d]{0,25}?(?:nr\.?|no\.?|number|seria)?\s*[:\-]?\s*([A-Z]{0,6}[\s\-]?\d[\w\-/]{1,20})", head)
    totals = {
        "total_net": _find(r"total\s*(?:f[aă]r[aă]|fara|excl\w*|net\w*)\s*(?:de\s*)?(?:tva|vat)?[^\d\n]{0,20}(" + NUM + ")", text),
        "total_vat": _find(r"total\s*tva(?:\s*\d{1,2}\s*%)?[^\d\n]{0,20}(" + NUM + ")", text) or _find(r"\btva\b[^\n\d]{0,15}(?:total)?[^\d\n]{0,10}(" + NUM + ")\s*$", text, re.I | re.M),
        "total_gross": _find(r"(?:total\s*(?:de\s*plat[aă]|general|factur[aă]|cu\s*tva)|grand\s*total|total\s*incl\w*)[^\d\n]{0,25}(" + NUM + ")", text),
    }
    currency = "EUR" if re.search(r"\bEUR\b|€", text) else "RON" if re.search(r"\bRON\b|\blei\b", text, re.I) else None
    return {
        "supplier_name": re.sub(r"\s+", " ", name) if name else None,
        "supplier_tax_id": re.sub(r"\s+", "", tax) if tax else None,
        "document_number": re.sub(r"\s+", "", number) if number else None,
        "issue_date": _parse_date(head),
        "currency": currency,
        **{k: parse_number(v) for k, v in totals.items()},
    }


def parse_text_invoice(text: str, tables: list | None = None) -> ExtractedInvoice:
    lines = _lines_from_tables(tables or []) or _lines_from_text(text)
    if not lines:
        raise InvoiceReadError(
            "No invoice lines could be recognised in this document. Upload the e-Factura XML instead, "
            "or ask an administrator to enable the AI reader for this layout."
        )
    document_type = "credit_note" if re.search(r"(?i)\b(storno|nota\s+de\s+credit|credit\s+note)\b", text[:1500]) else "invoice"
    return ExtractedInvoice(document_type=document_type, lines=lines, **_header(text))


def extract_locally(content: bytes, kind: str) -> ExtractedInvoice:
    text, tables = read_text(content, kind)
    return parse_text_invoice(text, tables)
