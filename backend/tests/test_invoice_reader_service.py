import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.invoice import InvoiceImport
from app.reader_app import app as reader_app
from app.services import invoice_reader
from app.services.invoice_intake import process_pending_reads
from tests.conftest import create_location
from tests.invoice_samples import invoice_pdf, ubl_invoice
from tests.test_invoice_intake import upload

BACKEND = Path(__file__).resolve().parents[1]
TOKEN = "reader-secret"


@pytest.fixture()
def reader():
    with TestClient(reader_app) as test_client:
        yield test_client


@pytest.fixture()
def remote(monkeypatch, reader):
    """Point the API at the reader service, running in-process, through a real HTTP request/response cycle."""
    state = {"down": False, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["down"]:
            raise httpx.ConnectError("reader is down")
        headers = {k: v for k, v in request.headers.items() if k.lower() in {"authorization", "content-type"}}
        if state.get("auth"):
            headers["authorization"] = state["auth"]            # simulate a client configured with another token
        answer = reader.post(request.url.path, params=dict(request.url.params), content=request.content, headers=headers)
        return httpx.Response(answer.status_code, content=answer.content, headers={"content-type": "application/json"})

    monkeypatch.setattr(invoice_reader, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(settings, "invoice_reader_url", "http://invoice-reader:8100")
    monkeypatch.setattr(settings, "invoice_reader_token", TOKEN)
    return state


def pending():
    with SessionLocal() as db:
        return process_pending_reads(db)


def invoice_row(invoice_id):
    with SessionLocal() as db:
        row = db.get(InvoiceImport, invoice_id)
        return {"status": row.status, "attempts": row.read_attempts, "error": row.error, "next": row.next_read_at}


def make_due(invoice_id):
    with SessionLocal() as db:
        db.get(InvoiceImport, invoice_id).next_read_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()


# ---------------------------------------------------------------- the service itself
def test_service_reads_pdf_and_requires_the_token(reader, monkeypatch):
    monkeypatch.setattr(settings, "invoice_reader_token", TOKEN)
    pdf = invoice_pdf()
    assert reader.post("/read", content=pdf).status_code == 401
    assert reader.post("/read", content=pdf, headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = reader.post("/read", content=pdf, headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["supplier_tax_id"] == "RO1234567" and len(body["lines"]) == 3
    assert reader.get("/health").json()["status"] == "ok"              # health needs no token (orchestrators probe it)


def test_service_errors_distinguish_bad_documents_from_bad_requests(reader, monkeypatch):
    monkeypatch.setattr(settings, "invoice_reader_token", None)
    assert reader.post("/read", content=b"").status_code == 400
    assert reader.post("/read", content=b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert reader.post("/read", content=b"\x00binary").status_code == 422
    assert reader.post("/read", content=ubl_invoice()).status_code == 422                      # XML is the API's job
    assert reader.post("/read", params={"kind": "docx"}, content=invoice_pdf()).status_code == 422
    blank = reader.post("/read", content=b"%PDF-1.4 garbage")
    assert blank.status_code == 422 and blank.json()["detail"]


def test_open_in_development_but_refuses_to_run_unprotected_in_production(reader, monkeypatch):
    monkeypatch.setattr(settings, "invoice_reader_token", None)
    assert reader.post("/read", content=invoice_pdf()).status_code == 200
    monkeypatch.setattr(settings, "app_env", "production")
    assert reader.post("/read", content=invoice_pdf()).status_code == 503


# ---------------------------------------------------------------- API <-> service
def test_upload_is_read_by_the_remote_service(client, tenant_a, remote):
    create_location(client, tenant_a)
    invoice = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf").json()
    assert invoice["status"] == "draft" and invoice["extracted"]["header"]["document_number"] == "FCT2026/0457"
    assert remote["calls"] == 1


def test_xml_never_goes_to_the_reader(client, tenant_a, remote):
    invoice = upload(client, tenant_a, ubl_invoice()).json()
    assert invoice["status"] == "draft" and remote["calls"] == 0


def test_unreadable_documents_fail_once_without_retrying(client, tenant_a, remote):
    result = upload(client, tenant_a, b"%PDF-1.4 garbage", filename="b.pdf", content_type="application/pdf").json()
    assert result["status"] == "failed" and remote["calls"] == 1


def test_reader_down_keeps_the_invoice_waiting_and_the_worker_retries(client, tenant_a, remote):
    create_location(client, tenant_a)
    remote["down"] = True
    queued = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf")
    assert queued.status_code == 201
    invoice = queued.json()
    assert invoice["status"] == "reading" and "could not be reached" in invoice["error"]
    state = invoice_row(invoice["id"])
    assert state["attempts"] == 1 and state["next"] > datetime.now(timezone.utc)
    assert pending() == 0                                              # not due yet: no new attempt

    make_due(invoice["id"])
    assert pending() == 1 and invoice_row(invoice["id"])["status"] == "reading" and invoice_row(invoice["id"])["attempts"] == 2

    remote["down"] = False                                              # the reader comes back
    make_due(invoice["id"])
    assert pending() == 1
    done = client.get(f"/api/invoices/{invoice['id']}", headers=tenant_a["headers"]).json()
    assert done["status"] == "draft" and done["error"] is None and len(done["extracted"]["lines"]) == 3


def test_worker_gives_up_after_the_attempt_limit(client, tenant_a, remote, monkeypatch):
    monkeypatch.setattr(settings, "invoice_read_max_attempts", 3)
    remote["down"] = True
    invoice = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf").json()
    for _ in range(5):
        if invoice_row(invoice["id"])["status"] == "reading":
            make_due(invoice["id"])
        pending()
    final = invoice_row(invoice["id"])
    assert final["status"] == "failed" and "gave up" in final["error"] and final["next"] is None
    assert client.get("/api/alerts", headers=tenant_a["headers"]).json()[0]["type"] == "invoices_unreadable"


def test_wrong_token_is_a_retryable_configuration_problem(client, tenant_a, remote):
    remote["auth"] = "Bearer wrong"
    invoice = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf").json()
    assert invoice["status"] == "reading" and "INVOICE_READER_TOKEN" in invoice["error"]
    remote["auth"] = None                                                          # operator fixes the config
    make_due(invoice["id"])
    pending()
    assert invoice_row(invoice["id"])["status"] == "draft"


# ---------------------------------------------------------------- background (async) mode
@pytest.fixture()
def async_mode(monkeypatch):
    monkeypatch.setattr(settings, "invoice_read_async", True)


def test_async_upload_returns_at_once_and_the_worker_reads_it(client, tenant_a, async_mode):
    create_location(client, tenant_a)
    queued = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf").json()
    assert queued["status"] == "reading" and queued["extracted"] is None and queued["blocking"] == []
    assert pending() == 1
    read = client.get(f"/api/invoices/{queued['id']}", headers=tenant_a["headers"]).json()
    assert read["status"] == "draft" and read["extracted"]["header"]["supplier_tax_id"] == "RO1234567"
    assert pending() == 0                                                         # nothing left to do


def test_async_mode_still_parses_xml_immediately(client, tenant_a, async_mode):
    assert upload(client, tenant_a, ubl_invoice()).json()["status"] == "draft"


def test_invoices_waiting_to_be_read_can_be_rejected_and_are_not_postable(client, tenant_a, async_mode):
    queued = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf").json()
    assert client.post(f"/api/invoices/{queued['id']}/post", headers=tenant_a["headers"], json={}).status_code == 409
    assert client.post(f"/api/invoices/{queued['id']}/reject", headers=tenant_a["headers"]).json()["status"] == "rejected"
    assert pending() == 0                                                         # rejected: the worker skips it


def test_a_document_that_keeps_crashing_the_worker_is_eventually_failed(client, tenant_a, async_mode, monkeypatch):
    monkeypatch.setattr(settings, "invoice_read_max_attempts", 2)
    queued = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf").json()
    for _ in range(3):                                                            # simulate leases that never finished
        with SessionLocal() as db:
            row = db.get(InvoiceImport, queued["id"])
            row.read_attempts += 1
            row.status, row.next_read_at = "reading", datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
    pending()
    assert invoice_row(queued["id"])["status"] == "failed"


def test_workers_do_not_read_the_same_invoice_twice(client, tenant_a, async_mode, monkeypatch):
    queued = upload(client, tenant_a, invoice_pdf(), filename="f.pdf", content_type="application/pdf").json()
    calls = []
    from app.services import invoice_intake

    original = invoice_intake.process_reading
    monkeypatch.setattr(invoice_intake, "process_reading", lambda db, inv: (calls.append(inv.id), original(db, inv))[1])
    pending()
    pending()
    assert calls == [queued["id"]]


# ---------------------------------------------------------------- command line
def run_cli(path):
    return subprocess.run([sys.executable, "-m", "app.reader_cli", str(path)], cwd=BACKEND, capture_output=True, text=True, env={"PATH": "/usr/bin:/usr/local/bin", "HOME": "/root", "PYTHONPATH": str(BACKEND)})


def test_cli_prints_the_extraction_as_json(tmp_path):
    pdf = tmp_path / "factura.pdf"
    pdf.write_bytes(invoice_pdf())
    result = run_cli(pdf)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["document_number"] == "FCT2026/0457" and len(data["lines"]) == 3


def test_cli_reports_unreadable_files_and_bad_usage(tmp_path):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"\x00\x01")
    assert run_cli(junk).returncode == 1
    xml = tmp_path / "f.xml"
    xml.write_bytes(ubl_invoice())
    assert run_cli(xml).returncode == 1 and "e-Factura XML is parsed by the API" in run_cli(xml).stderr
    assert subprocess.run([sys.executable, "-m", "app.reader_cli"], cwd=BACKEND, capture_output=True, env={"PATH": "/usr/bin", "PYTHONPATH": str(BACKEND)}).returncode == 2
