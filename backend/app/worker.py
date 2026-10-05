"""Background worker: runs scheduled POS synchronisations.

Run with ``python -m app.worker``. Several workers can run at once; due integrations are
claimed with ``FOR UPDATE SKIP LOCKED``.
"""

import logging
import signal
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.digest import send_alert_digests
from app.services.invoice_intake import process_pending_reads
from app.services.invoice_mail import poll_mailbox
from app.services.retention import purge_expired_data
from app.services.sync import fail_stale_runs, run_due_syncs

logger = logging.getLogger("horeca.worker")
_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


_last_digest_check = 0.0
_last_sync = 0.0
_last_purge = 0.0
_last_mail = 0.0
DIGEST_CHECK_SECONDS = 3600
PURGE_SECONDS = 86400
READ_POLL_SECONDS = 5  # invoice reading is checked more often than the other jobs


def _sync_due() -> bool:
    global _last_sync
    if time.monotonic() - _last_sync >= settings.worker_poll_seconds or _last_sync == 0.0:
        _last_sync = time.monotonic()
        return True
    return False


def tick() -> int:
    global _last_digest_check, _last_purge, _last_mail
    with SessionLocal() as db:
        fail_stale_runs(db)
        processed = run_due_syncs(db) if _sync_due() else 0
        reads = process_pending_reads(db)
        if reads:
            logger.info('{"event": "invoices_read", "count": %d}', reads)
        if time.monotonic() - _last_digest_check >= DIGEST_CHECK_SECONDS:
            _last_digest_check = time.monotonic()
            notified = send_alert_digests(db)
            if notified:
                logger.info('{"event": "alert_digest_sent", "companies": %d}', notified)
        if settings.imap_host and (_last_mail == 0.0 or time.monotonic() - _last_mail >= settings.invoice_poll_seconds):
            _last_mail = time.monotonic()
            mail = poll_mailbox(db)
            if mail["messages"]:
                logger.info('{"event": "invoice_mail_polled", "result": %s}', str(mail).replace("'", '"'))
        if time.monotonic() - _last_purge >= PURGE_SECONDS or _last_purge == 0.0:
            _last_purge = time.monotonic()
            removed = purge_expired_data(db, settings.audit_retention_days, settings.webhook_event_retention_days)
            if any(removed.values()):
                logger.info('{"event": "retention_purge", "removed": %s}', str(removed).replace("'", '"'))
        return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info('{"event": "worker_started", "poll_seconds": %d}', settings.worker_poll_seconds)
    while _running:
        try:
            processed = tick()
            if processed:
                logger.info('{"event": "worker_synced", "integrations": %d}', processed)
        except Exception:  # keep the worker alive; the next tick retries
            logger.exception('{"event": "worker_tick_failed"}')
        for _ in range(min(settings.worker_poll_seconds, READ_POLL_SECONDS)):
            if not _running:
                break
            time.sleep(1)
    logger.info('{"event": "worker_stopped"}')


if __name__ == "__main__":
    main()
