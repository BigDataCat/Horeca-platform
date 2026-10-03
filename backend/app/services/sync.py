from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pos_integration import POSIntegration
from app.models.sync_run import SyncRun
from app.services.pos_connectors import get_connector
from app.services.sales_ingestion import import_sale

MAX_CONSECUTIVE_FAILURES = 5
BASE_BACKOFF_MINUTES = 1
MAX_BACKOFF_MINUTES = 60
STALE_RUN_MINUTES = 15
CLAIM_LEASE_MINUTES = 15


@dataclass
class SyncOutcome:
    sync_run: SyncRun
    error: Exception | None = None


def backoff_minutes(failures: int) -> int:
    return min(BASE_BACKOFF_MINUTES * 2 ** max(failures - 1, 0), MAX_BACKOFF_MINUTES)


def run_sync(db: Session, integration: POSIntegration, trigger: str = "manual") -> SyncOutcome:
    """Pull and import sales for one integration, recording a SyncRun.

    Never raises for sync failures: the failure is persisted on the run and the integration,
    and returned in the outcome so callers can decide how to report it.
    """
    sync_run = SyncRun(
        company_id=integration.company_id,
        integration_id=integration.id,
        started_at=datetime.now(timezone.utc),
        status="running",
        trigger=trigger,
    )
    db.add(sync_run)
    db.commit()
    db.refresh(sync_run)
    run_id = sync_run.id
    integration_id = integration.id

    try:
        connector = get_connector(integration.provider)
        pull_result = connector.pull_sales(integration, integration.last_sync_cursor)
        sync_run.fetched = len(pull_result.sales)

        for sale in pull_result.sales:
            if import_sale(db, integration, sale):
                sync_run.imported += 1
            else:
                sync_run.skipped_duplicates += 1

        now = datetime.now(timezone.utc)
        integration.last_sync_cursor = pull_result.next_cursor
        integration.last_synced_at = now
        integration.status = "connected"
        integration.consecutive_failures = 0
        integration.sync_paused_reason = None
        if integration.sync_interval_minutes:
            integration.next_sync_at = now + timedelta(minutes=integration.sync_interval_minutes)
        sync_run.status = "success"
        sync_run.finished_at = now
        db.commit()
        return SyncOutcome(sync_run)

    except Exception as exc:
        db.rollback()
        sync_run = db.get(SyncRun, run_id)
        integration = db.get(POSIntegration, integration_id)
        now = datetime.now(timezone.utc)
        if sync_run is not None:
            sync_run.status = "error"
            sync_run.finished_at = now
            sync_run.error_message = str(exc)[:2000]
        if integration is not None:
            integration.status = "error"
            integration.consecutive_failures += 1
            if integration.sync_interval_minutes:
                if integration.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    integration.next_sync_at = None
                    integration.sync_paused_reason = (
                        f"Paused after {integration.consecutive_failures} consecutive failures: {str(exc)[:300]}"
                    )
                else:
                    integration.next_sync_at = now + timedelta(
                        minutes=backoff_minutes(integration.consecutive_failures)
                    )
        db.commit()
        return SyncOutcome(sync_run, exc)


def claim_due_integrations(db: Session, limit: int = 10) -> list[int]:
    """Select integrations due for a scheduled sync and lease them so other workers skip them."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(POSIntegration)
        .where(
            POSIntegration.active.is_(True),
            POSIntegration.sync_interval_minutes.is_not(None),
            POSIntegration.next_sync_at.is_not(None),
            POSIntegration.next_sync_at <= now,
        )
        .order_by(POSIntegration.next_sync_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for integration in rows:
        integration.next_sync_at = now + timedelta(minutes=CLAIM_LEASE_MINUTES)
    ids = [integration.id for integration in rows]
    db.commit()
    return ids


def fail_stale_runs(db: Session) -> int:
    """Mark runs stuck in 'running' (e.g. a crashed worker) as failed."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUN_MINUTES)
    stale = db.scalars(
        select(SyncRun).where(SyncRun.status == "running", SyncRun.started_at < cutoff)
    ).all()
    for run in stale:
        run.status = "error"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = "Run did not finish (worker stopped); marked failed"
    db.commit()
    return len(stale)


def run_due_syncs(db: Session, limit: int = 10) -> int:
    ids = claim_due_integrations(db, limit)
    for integration_id in ids:
        integration = db.get(POSIntegration, integration_id)
        if integration is not None and integration.active:
            run_sync(db, integration, trigger="scheduled")
    return len(ids)
