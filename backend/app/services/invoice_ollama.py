"""Optional: let a local LLM (Ollama, running on your own hardware) read the text of an invoice.

The text comes from the PDF text layer or OCR (see invoice_local); the model only structures it.
Nothing leaves your network. Output is validated like any other reader and always reviewed by a person."""

import json

import httpx

from app.core.config import settings
from app.schemas.invoices import ExtractedInvoice
from app.services.invoice_ai import SYSTEM_PROMPT, AIInvoice, ai_to_extracted
from app.services.invoice_parsing import InvoiceReadError

transport: httpx.BaseTransport | None = None  # tests inject a mock


def extract_with_ollama(text: str) -> ExtractedInvoice:
    if not settings.ollama_url:
        raise InvoiceReadError("The local LLM reader is not configured (OLLAMA_URL)")
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": AIInvoice.model_json_schema(),
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Extract this invoice. The text below is the document:\n\n" + text[:30000]},
        ],
    }
    try:
        with httpx.Client(timeout=settings.ollama_timeout_seconds, transport=transport) as client:
            response = client.post(settings.ollama_url.rstrip("/") + "/api/chat", json=payload)
        response.raise_for_status()
        content = response.json()["message"]["content"]
        parsed = AIInvoice.model_validate(json.loads(content))
    except httpx.HTTPError as exc:
        raise InvoiceReadError(f"The local LLM could not be reached ({exc.__class__.__name__})")
    except (ValueError, KeyError, TypeError):
        raise InvoiceReadError("The local LLM did not return a valid invoice")
    return ai_to_extracted(parsed)
