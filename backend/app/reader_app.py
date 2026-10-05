"""Invoice reader service: reads PDFs and photos and returns the extracted invoice as JSON.

Runs on its own (`uvicorn app.reader_app:app --port 8100`), without a database, so the heavy parts
(Tesseract OCR, PDF parsing, optional local or cloud LLM) can live in a separate container or machine.
The API/worker call it when INVOICE_READER_URL is set. It also keeps working standalone: see app/reader_cli.py."""

import hmac
import os

# The shared settings object requires a database URL; this service never uses one.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused")

from fastapi import FastAPI, Header, HTTPException, Query, Request, status  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.schemas.invoices import ExtractedInvoice  # noqa: E402
from app.services.invoice_parsing import MAX_FILE_BYTES, InvoiceReadError, detect_kind  # noqa: E402
from app.services.invoice_reader import read_document_locally  # noqa: E402

app = FastAPI(title="HoReCa invoice reader", version="1.0.0")


def _authorise(authorization: str | None) -> None:
    token = settings.invoice_reader_token
    if not token:
        if settings.app_env.lower() in {"production", "prod"}:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="INVOICE_READER_TOKEN is not set")
        return  # development: open
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid reader token")


@app.get("/health")
def health() -> dict:
    import shutil

    return {"status": "ok", "reader": settings.invoice_reader, "ocr": shutil.which("tesseract") is not None}


@app.post("/read", response_model=ExtractedInvoice)
async def read(request: Request, kind: str | None = Query(default=None, pattern="^(pdf|image)$"), authorization: str | None = Header(default=None)) -> ExtractedInvoice:
    """Raw PDF/PNG/JPEG/WEBP bytes in, extracted invoice out. 422 = this document cannot be read (do not retry);
    5xx = reader trouble (retry later)."""
    _authorise(authorization)
    body = await request.body()
    if not body or len(body) > MAX_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if body else status.HTTP_400_BAD_REQUEST, detail="Empty or oversized file")
    try:
        detected = detect_kind(body)
        if detected not in {"pdf", "image"}:
            raise InvoiceReadError("Only PDF and image files are read by this service")
        return read_document_locally(body, kind or detected)
    except InvoiceReadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
