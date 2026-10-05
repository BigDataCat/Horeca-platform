import json
import shutil
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.services import invoice_ai, invoice_local, invoice_ollama
from app.services.invoice_local import number_variants, parse_number
from tests.conftest import create_location, create_product
from tests.invoice_samples import ROWS, invoice_pdf, render_png, scanned_pdf
from tests.test_invoice_intake import patch, post, upload

needs_ocr = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")


@pytest.fixture(autouse=True)
def no_cloud(monkeypatch):
    """The default reader is local: prove nothing tries to reach the Claude API."""
    monkeypatch.setattr(settings, "invoice_reader", "local")

    def forbidden():
        raise AssertionError("the cloud reader must not be used by the local reader")

    monkeypatch.setattr(invoice_ai, "make_client", forbidden)


@pytest.mark.parametrize("raw,expected", [
    ("1.234,56", "1234.56"), ("1 234,5", "1234.5"), ("12.50", "12.50"), ("12,50", "12.50"),
    ("1,234.56", "1234.56"), ("0,5", "0.5"), ("-20,00", "-20.00"), ("425,00", "425.00"),
])
def test_number_formats(raw, expected):
    assert parse_number(raw) == Decimal(expected)


def test_ambiguous_thousands_keep_both_readings():
    assert set(number_variants("1.000")) == {Decimal("1000"), Decimal("1.000")}
    assert set(number_variants("3,000")) == {Decimal("3000"), Decimal("3.000")}
    assert number_variants("12,5") == [Decimal("12.5")]


def draft(response):
    assert response.status_code == 201, response.text
    return response.json()


def check_standard_invoice(invoice):
    assert invoice["status"] == "draft", invoice.get("error")
    header = invoice["extracted"]["header"]
    assert header["supplier_name"] == "METRO CASH & CARRY ROMANIA SRL"
    assert header["supplier_tax_id"] == "RO1234567"      # the supplier's CUI, not the buyer's
    assert header["document_number"] == "FCT2026/0457" and header["issue_date"] == "2026-10-02"
    assert (header["total_net"], header["total_vat"], header["total_gross"]) == ("765.00", "68.85", "833.85")
    lines = invoice["extracted"]["lines"]
    assert [(l["description"], l["unit"], Decimal(l["quantity"]), Decimal(l["unit_price"])) for l in lines] == [
        ("Carne de vita dezosata", "KG", Decimal("10"), Decimal("42.5")),
        ("Ulei floarea soarelui 1L", "EA", Decimal("24"), Decimal("7.5")),
        ("Faina alba tip 000", "KG", Decimal("50"), Decimal("3.2")),
    ]
    assert not any("add up" in w or "net total" in w for w in invoice["warnings"])
    assert invoice["warnings"][0].startswith("Read automatically")


@pytest.mark.parametrize("grid", [True, False])
def test_pdf_with_text_layer_is_read_locally(client, tenant_a, grid):
    invoice = draft(upload(client, tenant_a, invoice_pdf(grid=grid), filename="f.pdf", content_type="application/pdf"))
    check_standard_invoice(invoice)


@needs_ocr
def test_scanned_pdf_and_photo_are_read_with_ocr(client, tenant_a):
    pdf = invoice_pdf(grid=True)
    scanned = draft(upload(client, tenant_a, scanned_pdf(pdf), filename="scan.pdf", content_type="application/pdf"))
    check_standard_invoice(scanned)
    photo = draft(upload(client, tenant_a, render_png(invoice_pdf(grid=False), 200), filename="photo.png", content_type="image/png"))
    check_standard_invoice(photo)


@needs_ocr
@pytest.mark.parametrize("dpi", [90, 130, 160])
def test_poor_scans_are_never_silently_wrong(client, tenant_a, dpi):
    """OCR can misread digits (10,000 read as 19,000). A line is kept only if quantity x price matches its
    total, and anything dropped shows up as a mismatch against the invoice totals."""
    invoice = draft(upload(client, tenant_a, render_png(invoice_pdf(grid=False), dpi), filename="blurry.png", content_type="image/png"))
    if invoice["status"] != "draft":
        return  # refusing to read is acceptable
    for line in invoice["extracted"]["lines"]:
        assert abs(Decimal(line["quantity"]) * Decimal(line["unit_price"]) - Decimal(line["line_net"])) <= Decimal("0.05") + Decimal(line["line_net"]) * Decimal("0.005")
    if len(invoice["extracted"]["lines"]) < 3:
        assert any("net total" in w for w in invoice["warnings"])


def test_matching_review_and_posting_work_the_same_for_local_reads(client, tenant_a):
    from decimal import Decimal as D
    from tests.conftest import get_stock

    location = create_location(client, tenant_a, "Main")
    beef = create_product(client, tenant_a, "Carne de vita dezosata", base_uom="KG")
    oil = create_product(client, tenant_a, "Ulei floarea soarelui 1L", base_uom="EA")
    flour = create_product(client, tenant_a, "Faina alba tip 000", base_uom="KG")
    invoice = draft(upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf"))
    assert [l["match"] for l in invoice["extracted"]["lines"]] == ["name", "name", "name"] and invoice["blocking"] == []
    assert post(client, tenant_a, invoice["id"]).status_code == 200
    assert D(get_stock(client, tenant_a, location, flour)["quantity"]) == D("50")
    assert beef["id"] and oil["id"]


def test_romanian_number_formats_and_ambiguous_quantities_use_the_arithmetic(client, tenant_a):
    rows = [
        ("1", "Somon file", "kg", "2,000", "1.234,56", "2.469,12"),     # thousands separator in the price and the value
        ("2", "Lapte UHT 1L", "buc", "1.000", "2,50", "2.500,00"),      # '1.000' is a thousand (1000 x 2.50)
        ("3", "Zahar tos", "kg", "3,000", "12,50", "37,50"),            # '3,000' is three (3 x 12.50)
    ]
    invoice = draft(upload(client, tenant_a, invoice_pdf(grid=False, rows=rows, totals=("5.006,62", "450,59", "5.457,21")), filename="n.pdf", content_type="application/pdf"))
    quantities = [Decimal(l["quantity"]) for l in invoice["extracted"]["lines"]]
    assert quantities == [Decimal("2"), Decimal("1000"), Decimal("3")]
    assert not any("net total" in w for w in invoice["warnings"])


def test_totals_that_do_not_match_the_lines_are_flagged(client, tenant_a):
    invoice = draft(upload(client, tenant_a, invoice_pdf(totals=("999,00", "89,91", "1.088,91")), filename="x.pdf", content_type="application/pdf"))
    assert any("net total" in w for w in invoice["warnings"])


def test_storno_documents_are_recognised_and_blocked(client, tenant_a):
    create_location(client, tenant_a)
    invoice = draft(upload(client, tenant_a, invoice_pdf(storno=True), filename="s.pdf", content_type="application/pdf"))
    assert invoice["extracted"]["header"]["document_type"] == "credit_note"
    assert any("Credit notes" in b for b in invoice["blocking"])


def test_documents_without_recognisable_lines_fail_with_guidance(client, tenant_a):
    from reportlab.pdfgen import canvas
    import io

    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(72, 700, "Buna ziua, va trimitem oferta noastra de pret pentru luna viitoare.")
    page.showPage()
    page.save()
    result = draft(upload(client, tenant_a, buffer.getvalue(), filename="oferta.pdf", content_type="application/pdf"))
    assert result["status"] == "failed" and "e-Factura XML" in result["error"]


def test_missing_ocr_gives_a_clear_message(client, tenant_a, monkeypatch):
    monkeypatch.setattr(invoice_local, "_ocr_available", lambda: False)
    result = draft(upload(client, tenant_a, render_png(invoice_pdf()), filename="p.png", content_type="image/png"))
    assert result["status"] == "failed" and "OCR is not installed" in result["error"]


def test_broken_image_and_pdf_do_not_crash(client, tenant_a):
    assert draft(upload(client, tenant_a, b"\x89PNG\r\n\x1a\nnot really a png", filename="b.png", content_type="image/png"))["status"] == "failed"
    assert draft(upload(client, tenant_a, b"%PDF-1.4 garbage", filename="b.pdf", content_type="application/pdf"))["status"] == "failed"


def test_local_reads_are_never_auto_posted(client, tenant_a):
    from tests.test_invoice_intake import enable_auto

    create_location(client, tenant_a)
    for name in ("Carne de vita dezosata", "Ulei floarea soarelui 1L", "Faina alba tip 000"):
        create_product(client, tenant_a, name, base_uom="KG" if "Ulei" not in name else "EA")
    enable_auto(client, tenant_a)
    invoice = draft(upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf"))
    assert invoice["status"] == "draft"


# ---- optional local LLM
LLM_ANSWER = {
    "document_type": "invoice", "supplier_name": "Furnizor LLM SRL", "supplier_tax_id": "RO55", "document_number": "L1",
    "issue_date": "2026-10-02", "currency": "RON",
    "lines": [{"description": "Carne de vita dezosata", "quantity": 10, "unit": "kg", "unit_price": 42.5, "line_net": 425.0}],
    "total_net": 425.0, "total_vat": 38.25, "total_gross": 463.25,
}


@pytest.fixture()
def ollama(monkeypatch):
    monkeypatch.setattr(settings, "invoice_reader", "ollama")
    monkeypatch.setattr(settings, "ollama_url", "http://localhost:11434")
    seen = []

    def serve(handler):
        monkeypatch.setattr(invoice_ollama, "transport", httpx.MockTransport(lambda request: (seen.append(json.loads(request.content)), handler(request))[1]))

    yield serve, seen


def test_local_llm_structures_the_extracted_text(client, tenant_a, ollama):
    serve, seen = ollama
    serve(lambda request: httpx.Response(200, json={"message": {"content": json.dumps(LLM_ANSWER)}}))
    invoice = draft(upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf"))
    assert invoice["extracted"]["header"]["supplier_name"] == "Furnizor LLM SRL" and len(invoice["extracted"]["lines"]) == 1
    request = seen[0]
    assert request["stream"] is False and request["options"]["temperature"] == 0 and "format" in request
    assert "FACTURA FISCALA" in request["messages"][1]["content"]           # it receives text, not the file
    assert "untrusted" in request["messages"][0]["content"]


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500),
    lambda r: httpx.Response(200, json={"message": {"content": "not json at all"}}),
    lambda r: httpx.Response(200, json={"message": {"content": json.dumps({"lines": []})}}),
    lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
])
def test_local_llm_problems_fall_back_to_the_rule_reader(client, tenant_a, ollama, handler):
    serve, _ = ollama
    serve(handler)
    invoice = draft(upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf"))
    check_standard_invoice(invoice)


def test_local_llm_not_configured_falls_back(client, tenant_a, monkeypatch):
    monkeypatch.setattr(settings, "invoice_reader", "ollama")
    monkeypatch.setattr(settings, "ollama_url", None)
    check_standard_invoice(draft(upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf")))
