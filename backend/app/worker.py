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
from app.services.sync import fail_stale_runs, run_due_syncs

logger = logging.getLogger("horeca.worker")
_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


_last_digest_check = 0.0
DIGEST_CHECK_SECONDS = 3600


def tick() -> int:
    global _last_digest_check
    with SessionLocal() as db:
        fail_stale_runs(db)
        processed = run_due_syncs(db)
        if time.monotonic() - _last_digest_check >= DIGEST_CHECK_SECONDS:
            _last_digest_check = time.monotonic()
            notified = send_alert_digests(db)
            if notified:
                logger.info('{"event": "alert_digest_sent", "companies": %d}', notified)
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
        for _ in range(settings.worker_poll_seconds):
            if not _running:
                break
            time.sleep(1)
    logger.info('{"event": "worker_stopped"}')


if __name__ == "__main__":
    main()
