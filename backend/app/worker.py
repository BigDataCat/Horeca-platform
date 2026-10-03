"""Background worker: runs scheduled POS synchronisations.

Run with ``python -m app.worker``. Several workers can run at once; due integrations are
claimed with ``FOR UPDATE SKIP LOCKED``.
"""

import logging
import signal
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.sync import fail_stale_runs, run_due_syncs

logger = logging.getLogger("horeca.worker")
_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


def tick() -> int:
    with SessionLocal() as db:
        fail_stale_runs(db)
        return run_due_syncs(db)


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
