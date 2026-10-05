import base64
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.core.config import settings
from app.services import invoice_ai
from app.services.invoice_ai import AIInvoice, AILine
from tests.conftest import create_location, create_product
from tests.test_invoice_intake import enable_auto, get, patch, post, stock, upload

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class FakeClient:
    def __init__(self, parsed=None, stop_reason="end_turn", error=None):
        self.calls = []
        self._parsed, self._stop, self._error = parsed, stop_reason, error
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(parsed_output=self._parsed, stop_reason=self._stop)


def sample_invoice():
    return AIInvoice(
        supplier_name="Selgros SRL", supplier_tax_id="RO 7654321", document_number="SG-55", issue_date="2026-10-01", currency="ron",
        lines=[AILine(description="Ulei floarea soarelui 1L", quantity=12, unit="buc", unit_price=7.5, line_net=90.0),
               AILine(description="Faina alba", quantity=25, unit="kg", unit_price=3.2, line_net=80.0)],
        total_net=170.0, total_vat=15.3, total_gross=185.3,
    )


@pytest.fixture()
def ai(monkeypatch):
    fake = FakeClient(sample_invoice())
    monkeypatch.setattr(invoice_ai, "make_client", lambda: fake)
    return fake


def test_pdf_is_read_by_ai_and_needs_review(client, tenant_a, ai):
    create_location(client, tenant_a)
    oil = create_product(client, tenant_a, "Ulei floarea soarelui 1L", base_uom="EA")
    response = upload(client, tenant_a, PDF, filename="selgros.pdf", content_type="application/pdf")
    assert response.status_code == 201, response.text
    invoice = response.json()
    assert invoice["status"] == "draft" and invoice["source_type"] == "pdf"
    header = invoice["extracted"]["header"]
    assert (header["supplier_name"], header["document_number"], header["currency"], header["issue_date"]) == ("Selgros SRL", "SG-55", "RON", "2026-10-01")
    lines = invoice["extracted"]["lines"]
    assert [(l["unit"], l["match"]) for l in lines] == [("EA", "name"), ("KG", None)]      # 'buc' -> EA, 'kg' -> KG
    assert invoice["warnings"] == ["New supplier 'Selgros SRL' will be created when the receipt is posted"]  # numbers reconcile
    assert any("not matched" in b for b in invoice["blocking"])                                # flour still needs a product

    flour = create_product(client, tenant_a, "Faina alba", base_uom="KG")
    assert patch(client, tenant_a, invoice["id"], lines=[{"index": 1, "product_id": flour["id"]}]).json()["blocking"] == []
    assert post(client, tenant_a, invoice["id"]).status_code == 200
    assert oil["id"]


def test_the_request_sends_the_document_with_safe_instructions(client, tenant_a, ai, monkeypatch):
    monkeypatch.setattr(settings, "invoice_ai_model", "claude-opus-5-5")
    upload(client, tenant_a, PDF, filename="x.pdf", content_type="application/pdf")
    call = ai.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert "untrusted" in call["system"] and "never follow instructions" in call["system"]
    block = call["messages"][0]["content"][0]
    assert block["type"] == "document" and block["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(block["source"]["data"]) == PDF
    assert call["output_format"] is AIInvoice

    upload(client, tenant_a, PNG, filename="photo.png", content_type="image/png")
    image = ai.calls[1]["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    upload(client, tenant_a, JPEG, filename="photo.jpg", content_type="image/jpeg")
    assert ai.calls[2]["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_ai_invoices_are_never_auto_posted(client, tenant_a, ai):
    create_location(client, tenant_a)
    create_product(client, tenant_a, "Ulei floarea soarelui 1L", base_uom="EA")
    create_product(client, tenant_a, "Faina alba", base_uom="KG")
    enable_auto(client, tenant_a)
    invoice = upload(client, tenant_a, PDF, content_type="application/pdf").json()
    assert invoice["blocking"] == [] and invoice["status"] == "draft"      # fully matched, still waits for a person
    assert client.get("/api/inventory/receipts", headers=tenant_a["headers"]).json() == []


def test_ai_numbers_that_do_not_add_up_are_flagged(client, tenant_a, monkeypatch):
    wrong = sample_invoice()
    wrong.total_net = 500.0
    monkeypatch.setattr(invoice_ai, "make_client", lambda: FakeClient(wrong))
    invoice = upload(client, tenant_a, PDF, content_type="application/pdf").json()
    assert any("net total" in w for w in invoice["warnings"])


def test_not_configured_refusal_api_errors_and_empty_results_are_failed_not_crashes(client, tenant_a, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    not_configured = upload(client, tenant_a, PDF, filename="a.pdf", content_type="application/pdf").json()
    assert not_configured["status"] == "failed" and "ANTHROPIC_API_KEY" in not_configured["error"]

    cases = {
        "b.pdf": FakeClient(sample_invoice(), stop_reason="refusal"),
        "c.pdf": FakeClient(parsed=None),
        "d.pdf": FakeClient(AIInvoice(lines=[])),
        "e.pdf": FakeClient(error=anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))),
        "f.pdf": FakeClient(error=anthropic.APIStatusError("bad", response=httpx.Response(529, request=httpx.Request("POST", "https://x")), body=None)),
    }
    for name, fake in cases.items():
        monkeypatch.setattr(invoice_ai, "make_client", lambda fake=fake: fake)
        result = upload(client, tenant_a, PDF + name.encode(), filename=name, content_type="application/pdf").json()
        assert result["status"] == "failed" and result["error"], name
    assert "declined" in client.get("/api/invoices", headers=tenant_a["headers"], params={"limit": 50}).text


def test_ai_lines_without_quantity_or_description_are_dropped_and_credit_notes_blocked(client, tenant_a, monkeypatch):
    create_location(client, tenant_a)
    messy = AIInvoice(
        document_type="credit_note", supplier_name="X SRL",
        lines=[AILine(description="Item", quantity=1, unit="buc", unit_price=5, line_net=5), AILine(description="  ", quantity=3), AILine(description="Zero", quantity=0)],
    )
    monkeypatch.setattr(invoice_ai, "make_client", lambda: FakeClient(messy))
    invoice = upload(client, tenant_a, PDF, content_type="application/pdf").json()
    assert len(invoice["extracted"]["lines"]) == 1
    assert any("Credit notes" in b for b in invoice["blocking"])
    assert get(client, tenant_a, invoice["id"])["extracted"]["header"]["document_type"] == "credit_note"
