"""Choose how PDF/photo invoices are read. XML never comes here (it is parsed exactly).

INVOICE_READER:
  local   (default) PDF text / OCR + rules, entirely on this server
  ollama            same text extraction, then a local LLM structures it; falls back to the rules
  claude            send the document to the Claude API (cloud)"""

import logging

from app.core.config import settings
from app.schemas.invoices import ExtractedInvoice
from app.services.invoice_parsing import InvoiceReadError

logger = logging.getLogger("horeca.invoice_reader")


def read_document(content: bytes, kind: str) -> ExtractedInvoice:
    reader = settings.invoice_reader
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
