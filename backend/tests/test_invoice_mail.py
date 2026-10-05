from decimal import Decimal
from email.message import EmailMessage

import pytest

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.invoice_mail import poll_mailbox
from tests.conftest import create_location, create_product, get_stock
from tests.invoice_samples import efactura_zip, ubl_invoice
from tests.test_invoice_intake import enable_auto
from tests.test_invoice_ai import PDF, FakeClient, sample_invoice


class FakeIMAP:
    """Just enough of imaplib.IMAP4 for the poller."""

    def __init__(self, raw_messages):
        self.messages = {str(i + 1).encode(): raw for i, raw in enumerate(raw_messages)}
        self.seen: set[bytes] = set()
        self.logged_out = False

    def select(self, folder):
        return "OK", [b"1"]

    def search(self, charset, criterion):
        assert criterion == "UNSEEN"
        return "OK", [b" ".join(n for n in self.messages if n not in self.seen)]

    def fetch(self, number, parts):
        assert "PEEK" in parts                              # never marks the message seen by itself
        return "OK", [(b"1 (BODY[] {10}", self.messages[number]), b")"]

    def store(self, number, op, flags):
        assert (op, flags) == ("+FLAGS", "\\Seen")
        self.seen.add(number)

    def logout(self):
        self.logged_out = True


def mail(to, attachments, subject="Factura", extra_headers=None):
    message = EmailMessage()
    message["From"] = "facturi@furnizor.ro"
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = f"<{subject}-{abs(hash(str(attachments)))}@furnizor.ro>"
    for key, value in (extra_headers or {}).items():
        message[key] = value
    message.set_content("Atasat factura.")
    for filename, content_type, payload in attachments:
        maintype, subtype = content_type.split("/")
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()


@pytest.fixture(autouse=True)
def mailbox_settings(monkeypatch):
    monkeypatch.setattr(settings, "invoice_inbox_address", "invoices@platform.example")
    monkeypatch.setattr(settings, "imap_host", "imap.platform.example")


@pytest.fixture()
def company(client, tenant_a):
    create_location(client, tenant_a, "Main")
    inbox = client.post("/api/invoices/inbox/token", headers=tenant_a["headers"]).json()
    assert inbox["address"].startswith("invoices+") and inbox["address"].endswith("@platform.example")
    return tenant_a, inbox["address"]


def poll(raw_messages):
    fake = FakeIMAP(raw_messages)
    with SessionLocal() as db:
        return poll_mailbox(db, factory=lambda: fake), fake


def invoices(client, tenant):
    return client.get("/api/invoices", headers=tenant["headers"]).json()


def test_attachments_from_the_company_address_become_drafts(client, company):
    tenant, address = company
    xml = ubl_invoice()
    result, fake = poll([mail(address, [("factura.xml", "application/xml", xml)])])
    assert result == {"messages": 1, "imported": 1, "duplicates": 0, "failed": 0, "unrouted": 0}
    assert fake.seen == {b"1"} and fake.logged_out
    [invoice] = invoices(client, tenant)
    assert invoice["source"] == "email" and invoice["status"] == "draft" and invoice["filename"] == "factura.xml"
    assert invoice["extracted"]["header"]["document_number"] == "FCT-100"


def test_routing_by_plus_address_headers_and_unknown_tokens(client, company, tenant_b):
    tenant, address = company
    other_address = client.post("/api/invoices/inbox/token", headers=tenant_b["headers"]).json()["address"]
    xml_a, xml_b = ubl_invoice(number="A"), ubl_invoice(number="B")
    stranger = "invoices+deadbeefdeadbeef@platform.example"
    result, fake = poll([
        mail(f"Contabilitate <{address}>", [("a.xml", "application/xml", xml_a)]),
        mail("someone@else.ro", [("b.xml", "text/xml", xml_b)], extra_headers={"Delivered-To": other_address}),  # alias/forwarding
        mail(stranger, [("c.xml", "application/xml", ubl_invoice(number="C"))]),
        mail("someone@else.ro", [("d.xml", "application/xml", ubl_invoice(number="D"))]),
    ])
    assert result["imported"] == 2 and result["unrouted"] == 2
    assert [i["extracted"]["header"]["document_number"] for i in invoices(client, tenant)] == ["A"]
    assert [i["extracted"]["header"]["document_number"] for i in invoices(client, tenant_b)] == ["B"]
    assert fake.seen == {b"1", b"2", b"3", b"4"}


def test_duplicates_signatures_and_unsupported_attachments_are_ignored(client, company):
    tenant, address = company
    xml = ubl_invoice()
    logo = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100                                    # tiny image = e-mail signature
    result, _ = poll([
        mail(address, [("factura.xml", "application/xml", xml), ("logo.png", "image/png", logo), ("notes.txt", "text/plain", b"hi"), ("scan.xlsx", "application/vnd.ms-excel", b"x")]),
        mail(address, [("again.xml", "application/xml", xml)], subject="Reminder"),
    ])
    assert result["imported"] == 1 and result["duplicates"] == 1 and result["failed"] == 0
    assert len(invoices(client, tenant)) == 1


def test_zip_and_pdf_attachments(client, company, monkeypatch):
    from app.services import invoice_ai

    tenant, address = company
    monkeypatch.setattr(invoice_ai, "make_client", lambda: FakeClient(sample_invoice()))
    result, _ = poll([mail(address, [("123.zip", "application/zip", efactura_zip(ubl_invoice(number="Z1"))), ("scan.pdf", "application/pdf", PDF)])])
    assert result["imported"] == 2
    assert sorted(i["source_type"] for i in invoices(client, tenant)) == ["pdf", "ubl_xml"]


def test_seen_messages_are_not_processed_again_and_failed_messages_stay_unseen(client, company, monkeypatch):
    tenant, address = company
    raw = [mail(address, [("a.xml", "application/xml", ubl_invoice())])]
    fake = FakeIMAP(raw)
    with SessionLocal() as db:
        poll_mailbox(db, factory=lambda: fake)
        assert poll_mailbox(db, factory=lambda: fake)["messages"] == 0

    from app.services import invoice_mail

    boom = FakeIMAP([mail(address, [("b.xml", "application/xml", ubl_invoice(number="B"))])])
    monkeypatch.setattr(invoice_mail, "process_message", lambda db, raw: (_ for _ in ()).throw(RuntimeError("db down")))
    with SessionLocal() as db:
        assert poll_mailbox(db, factory=lambda: boom)["messages"] == 0
    assert boom.seen == set()                                                      # retried next poll


def test_auto_post_applies_to_exact_xml_arriving_by_mail(client, company):
    tenant, address = company
    beef = create_product(client, tenant, "Carne vita", sku="SKU-1", base_uom="KG")
    salt = create_product(client, tenant, "Sare fina", base_uom="EA")
    enable_auto(client, tenant)
    poll([mail(address, [("factura.xml", "application/xml", ubl_invoice())])])
    [invoice] = invoices(client, tenant)
    assert invoice["status"] == "posted"
    location = client.get("/api/locations", headers=tenant["headers"]).json()[0]
    assert Decimal(get_stock(client, tenant, location, beef)["quantity"]) == Decimal("10")


def test_inactive_company_and_missing_configuration(client, company, monkeypatch):
    tenant, address = company
    from app.models.company import Company

    with SessionLocal() as db:
        db.get(Company, tenant["company_id"]).active = False
        db.commit()
    result, _ = poll([mail(address, [("a.xml", "application/xml", ubl_invoice())])])
    assert result["imported"] == 0 and result["unrouted"] == 1
    monkeypatch.setattr(settings, "imap_host", None)
    with SessionLocal() as db:
        assert poll_mailbox(db)["messages"] == 0                                    # nothing configured: no connection attempted


def test_inbox_info_token_rotation_and_settings(client, tenant_a, employee_a, manager_a):
    before = client.get("/api/invoices/inbox", headers=tenant_a["headers"]).json()
    assert before["address"] is None and before["configured"] is True
    first = client.post("/api/invoices/inbox/token", headers=tenant_a["headers"]).json()["address"]
    second = client.post("/api/invoices/inbox/token", headers=tenant_a["headers"]).json()["address"]
    assert first != second and client.get("/api/invoices/inbox", headers=employee_a["headers"]).json()["address"] == second
    # the old address stops working
    token_a = first.split("+")[1].split("@")[0]
    result, _ = poll([mail(first, [("a.xml", "application/xml", ubl_invoice())])])
    assert result["unrouted"] == 1 and token_a not in second
    other = create_location(client, tenant_a, "Second")
    ok = client.patch("/api/invoices/inbox", headers=tenant_a["headers"], json={"default_location_id": other["id"]})
    assert ok.json()["default_location_id"] == other["id"]
    assert client.patch("/api/invoices/inbox", headers=tenant_a["headers"], json={"default_location_id": 99999}).status_code == 404
