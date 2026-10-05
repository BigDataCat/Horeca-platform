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
