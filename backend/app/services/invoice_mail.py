"""Invoice e-mail intake: one shared mailbox, one address per company (invoices+TOKEN@domain).

Suppliers e-mail their invoices to the company's address; the worker polls the mailbox and turns every
invoice attachment into a draft (or an automatic receipt for exact XML invoices, if the company enabled it)."""

import imaplib
import logging
import re
from collections.abc import Callable
from email import message_from_bytes, policy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.company import Company
from app.services.invoice_intake import DuplicateInvoice, import_invoice
from app.services.invoice_parsing import InvoiceReadError

logger = logging.getLogger("horeca.invoice_mail")

ATTACHMENT_EXTENSIONS = (".xml", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".zip")
ATTACHMENT_TYPES = {"application/xml", "text/xml", "application/pdf", "image/png", "image/jpeg", "image/webp", "application/zip", "application/x-zip-compressed"}
MIN_IMAGE_BYTES = 15 * 1024  # smaller images are signature logos, not photographed invoices
RECIPIENT_HEADERS = ("Delivered-To", "X-Original-To", "Envelope-To", "To", "Cc")


def _token_pattern() -> re.Pattern | None:
    address = settings.invoice_inbox_address
    if not address or "@" not in address:
        return None
    local, domain = address.lower().split("@", 1)
    return re.compile(rf"{re.escape(local)}\+([0-9a-f]{{8,64}})@{re.escape(domain)}")


def find_token(message) -> str | None:
    pattern = _token_pattern()
    if pattern is None:
        return None
    for header in RECIPIENT_HEADERS:
        for value in message.get_all(header, []):
            match = pattern.search(str(value).lower())
            if match:
                return match.group(1)
    return None


def invoice_attachments(message):
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename() or ""
        content_type = part.get_content_type()
        lowered = filename.lower()
        if not (lowered.endswith(ATTACHMENT_EXTENSIONS) or (content_type in ATTACHMENT_TYPES and not part.get_content_disposition() == "inline")):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        if content_type.startswith("image/") and len(payload) < MIN_IMAGE_BYTES:
            continue
        yield filename or "attachment", content_type, payload


def process_message(db: Session, raw: bytes) -> dict[str, int]:
    """Import the attachments of one message. Returns counters: imported, duplicates, failed, skipped."""
    result = {"imported": 0, "duplicates": 0, "failed": 0, "unrouted": 0}
    message = message_from_bytes(raw, policy=policy.default)
    token = find_token(message)
    company = db.scalar(select(Company).where(Company.invoice_inbox_token == token, Company.active.is_(True))) if token else None
    if company is None:
        result["unrouted"] = 1  # not for a known company: nothing is stored
        return result
    message_id = str(message.get("Message-ID") or "")[:300] or None
    for filename, content_type, payload in invoice_attachments(message):
        try:
            import_invoice(db, company, None, payload, filename, content_type, source="email", mail_message_id=message_id)
            result["imported"] += 1
        except DuplicateInvoice:
            result["duplicates"] += 1
        except InvoiceReadError as exc:
            result["failed"] += 1
            logger.info('{"event": "invoice_mail_attachment_skipped", "company_id": %d, "reason": "%s"}', company.id, str(exc)[:120])
    return result


def default_imap_factory() -> imaplib.IMAP4:
    connection = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    connection.login(settings.imap_user or "", settings.imap_password or "")
    return connection


def poll_mailbox(db: Session, factory: Callable[[], imaplib.IMAP4] | None = None, limit: int = 50) -> dict[str, int]:
    """Process unseen messages. A message is marked seen only after it was handled, so a crash retries it."""
    totals = {"messages": 0, "imported": 0, "duplicates": 0, "failed": 0, "unrouted": 0}
    if not (settings.imap_host and settings.invoice_inbox_address) and factory is None:
        return totals
    connection = (factory or default_imap_factory)()
    try:
        connection.select(settings.imap_folder)
        status, data = connection.search(None, "UNSEEN")
        if status != "OK":
            return totals
        for number in data[0].split()[:limit]:
            status, fetched = connection.fetch(number, "(BODY.PEEK[])")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            try:
                counts = process_message(db, fetched[0][1])
            except Exception:
                db.rollback()
                logger.exception('{"event": "invoice_mail_message_failed"}')
                continue  # left unseen: retried on the next poll
            totals["messages"] += 1
            for key, value in counts.items():
                totals[key] += value
            connection.store(number, "+FLAGS", "\\Seen")
    finally:
        try:
            connection.logout()
        except Exception:
            pass
    return totals
