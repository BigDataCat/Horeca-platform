"""Read PDF and photo invoices. XML never comes here (it is parsed exactly in the API).

Where the reading happens:
  INVOICE_READER_URL set   a separate reader service does it (see app/reader_app.py)
  otherwise                in this process, using INVOICE_READER:
      local   (default) PDF text / OCR + rules, entirely on this server
      ollama            same text extraction, then a local LLM structures it; falls back to the rules
      claude            send the document to the Claude API (cloud)"""

import logging

import httpx

from app.core.config import settings
from app.schemas.invoices import ExtractedInvoice
from app.services.invoice_parsing import InvoiceReadError

logger = logging.getLogger("horeca.invoice_reader")

transport: httpx.BaseTransport | None = None  # tests can point the client at the reader app in-process


class ReaderUnavailable(Exception):
    """The reader service could not be reached or failed: the document may be fine, try again later."""


def read_document(content: bytes, kind: str) -> ExtractedInvoice:
    if settings.invoice_reader_url:
        return read_remotely(content, kind)
    return read_document_locally(content, kind)


def read_remotely(content: bytes, kind: str) -> ExtractedInvoice:
    headers = {"Content-Type": "application/octet-stream"}
    if settings.invoice_reader_token:
        headers["Authorization"] = f"Bearer {settings.invoice_reader_token}"
    try:
        with httpx.Client(timeout=settings.invoice_reader_timeout_seconds, transport=transport) as client:
            response = client.post(settings.invoice_reader_url.rstrip("/") + "/read", params={"kind": kind}, content=content, headers=headers)
    except httpx.HTTPError as exc:
        raise ReaderUnavailable(f"The invoice reader service could not be reached ({exc.__class__.__name__})")
    if response.status_code == 422:
        raise InvoiceReadError(str(response.json().get("detail", "The document could not be read")))
    if response.status_code in {401, 403}:
        raise ReaderUnavailable("The invoice reader service rejected the credentials (check INVOICE_READER_TOKEN)")
    if response.status_code >= 400:
        raise ReaderUnavailable(f"The invoice reader service failed (HTTP {response.status_code})")
    try:
        return ExtractedInvoice.model_validate(response.json())
    except ValueError:
        raise ReaderUnavailable("The invoice reader service returned an invalid answer")


def read_document_locally(content: bytes, kind: str) -> ExtractedInvoice:
    reader = settings.invoice_reader
    try:
        return _read_in_process(content, kind, reader)
    except ImportError:
        raise InvoiceReadError(
            "This server has no PDF/OCR reader installed. Run the invoice-reader service and set INVOICE_READER_URL, "
            "or upload the e-Factura XML."
        )


def _read_in_process(content: bytes, kind: str, reader: str) -> ExtractedInvoice:
    if reader == "claude":
        from app.services.invoice_ai import extract_with_ai

        return extract_with_ai(content, kind)

    from app.services import invoice_local

    if reader == "ollama":
        from app.services.invoice_ollama import extract_with_ollama

        text, tables = invoice_local.read_text(content, kind)
        try:
            invoice = extract_with_ollama(text)
            if invoice.lines:
                return invoice
        except InvoiceReadError as exc:
            logger.info('{"event": "ollama_reader_fallback", "reason": "%s"}', str(exc)[:120])
        return invoice_local.parse_text_invoice(text, tables)

    return invoice_local.extract_locally(content, kind)
