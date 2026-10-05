"""Builders for realistic e-Factura (UBL 2.1 / CIUS-RO) invoices used in tests."""
import io
import zipfile
from decimal import Decimal

NS = (
    'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
    'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"'
)


def ubl_invoice(
    number="FCT-100",
    date="2026-10-02",
    supplier="Metro Cash & Carry SRL",
    tax_id="RO1234567",
    lines=None,
    total_net=None,
    total_vat=None,
    total_gross=None,
    kind="Invoice",
):
    """lines: list of (name, qty, unit_code, unit_price, sku). Amounts are net."""
    lines = lines or [("Carne vita", "10", "KGM", "42.50", "SKU-1"), ("Sare fina", "20", "H87", "1.20", "SKU-2")]
    net = sum((Decimal(q) * Decimal(p) for _, q, _, p, _ in lines), Decimal(0))
    vat = (net * Decimal("0.09")).quantize(Decimal("0.01"))
    total_net = net if total_net is None else Decimal(total_net)
    total_vat = vat if total_vat is None else Decimal(total_vat)
    total_gross = (net + vat) if total_gross is None else Decimal(total_gross)
    line_tag = "InvoiceLine" if kind == "Invoice" else "CreditNoteLine"
    qty_tag = "InvoicedQuantity" if kind == "Invoice" else "CreditedQuantity"
    xml_lines = ""
    for index, (name, qty, unit, price, sku) in enumerate(lines, start=1):
        line_net = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
        xml_lines += f"""
  <cac:{line_tag}>
    <cbc:ID>{index}</cbc:ID>
    <cbc:{qty_tag} unitCode="{unit}">{qty}</cbc:{qty_tag}>
    <cbc:LineExtensionAmount currencyID="RON">{line_net}</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>{name}</cbc:Name>
      <cac:SellersItemIdentification><cbc:ID>{sku}</cbc:ID></cac:SellersItemIdentification>
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>9</cbc:Percent></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="RON">{price}</cbc:PriceAmount></cac:Price>
  </cac:{line_tag}>"""
    root = "Invoice" if kind == "Invoice" else "CreditNote"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<{root} {NS.replace('Invoice-2', root + '-2')}>
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:efactura.mfinante.ro:CIUS-RO:1.0.1</cbc:CustomizationID>
  <cbc:ID>{number}</cbc:ID>
  <cbc:IssueDate>{date}</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>RON</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyTaxScheme><cbc:CompanyID>{tax_id}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>{supplier}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="RON">{total_vat}</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="RON">{net}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="RON">{total_net}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="RON">{total_gross}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="RON">{total_gross}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>{xml_lines}
</{root}>""".replace("&", "&amp;").replace("&amp;amp;", "&amp;").encode()


def efactura_zip(xml: bytes, number="FCT-100") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{number}.xml", xml)
        archive.writestr(f"semnatura_{number}.xml", b"<Signature>not an invoice</Signature>")
    return buffer.getvalue()


# ---------------------------------------------------------------- PDF / image invoices (generated)
ROWS = [
    ("1", "Carne de vita dezosata", "kg", "10,000", "42,50", "425,00"),
    ("2", "Ulei floarea soarelui 1L", "buc", "24,000", "7,50", "180,00"),
    ("3", "Faina alba tip 000", "kg", "50,000", "3,20", "160,00"),
]
HEADER_ROW = ("Nr.", "Denumire produs", "U.M.", "Cantitate", "Pret unitar", "Valoare fara TVA")


def _header_lines(number="FCT 2026/0457", storno=False):
    title = "FACTURA STORNO" if storno else "FACTURA FISCALA"
    return [
        "Furnizor: METRO CASH & CARRY ROMANIA SRL",
        "CUI: RO 1234567  Reg. Com.: J40/1234/2001",
        "Adresa: Str. Exemplu 10, Bucuresti",
        "Client: RESTAURANT EXEMPLU SRL",
        "CUI: RO 7654321",
        f"{title} Nr. {number}",
        "Data emiterii: 02.10.2026",
    ]


def _footer_lines(net="765,00", vat="68,85", gross="833,85"):
    return [f"Total fara TVA: {net} RON", f"Total TVA 9%: {vat} RON", f"Total de plata: {gross} RON"]


def invoice_pdf(grid=True, rows=None, number="FCT 2026/0457", storno=False, totals=None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table, TableStyle

    rows = rows or ROWS
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    c.setFont("Helvetica", 11)
    for line in _header_lines(number, storno):
        c.drawString(40, y, line)
        y -= 16
    y -= 12
    if grid:
        table = Table([HEADER_ROW, *rows], colWidths=[28, 190, 40, 70, 80, 100])
        style = [("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 9)]
        table.setStyle(TableStyle(style))
        w, h = table.wrapOn(c, 520, 400)
        table.drawOn(c, 40, y - h)
        y -= h + 24
    else:
        c.setFont("Courier", 9)
        c.drawString(40, y, "Nr  Denumire produs              UM    Cantitate   Pret      Valoare")
        y -= 14
        for r in rows:
            c.drawString(40, y, f"{r[0]:<3} {r[1]:<28} {r[2]:<5} {r[3]:>9}  {r[4]:>8}  {r[5]:>9}")
            y -= 14
        y -= 10
        c.setFont("Helvetica", 11)
    for line in _footer_lines(*(totals or ())):
        c.drawString(300, y, line)
        y -= 16
    c.showPage()
    c.save()
    return buffer.getvalue()


def render_png(pdf: bytes, resolution=200) -> bytes:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as document:
        image = document.pages[0].to_image(resolution=resolution).original.convert("RGB")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def scanned_pdf(pdf: bytes) -> bytes:
    """An image-only PDF (no text layer), like a scanner produces."""
    from PIL import Image

    image = Image.open(io.BytesIO(render_png(pdf))).convert("RGB")
    out = io.BytesIO()
    image.save(out, "PDF", resolution=200)
    return out.getvalue()
