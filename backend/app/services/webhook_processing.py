import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.pos_integration import POSIntegration
from app.models.webhook_event import WebhookEvent
from app.schemas.sales import CanonicalSale
from app.services.sales_ingestion import apply_sale_status_event, import_sale

STATUS_EVENTS = {"sale.cancelled": "cancelled", "sale.refunded": "refunded"}


def process_webhook_event(db: Session, integration: POSIntegration, event: WebhookEvent) -> bool:
    """Import the sale stored on ``event``.

    Returns True when a new sale was imported and False when it already existed.
    On failure the transaction is rolled back, the event is persisted as ``failed``
    with the error (so it can be replayed) and the exception is re-raised.
    """
    event_id = event.id
    try:
        sale = CanonicalSale.model_validate(json.loads(event.payload or "{}").get("sale"))
        event.attempts += 1
        new_status = STATUS_EVENTS.get(event.event_type)
        if new_status is not None:
            imported = apply_sale_status_event(db, integration, sale, new_status)
        else:
            imported = import_sale(db, integration, sale)
        event.status = "processed" if imported else "duplicate_sale"
        event.error_message = None
        event.processed_at = datetime.now(timezone.utc)
        db.commit()
        return imported
    except Exception as exc:
        db.rollback()
        failed = db.get(WebhookEvent, event_id)
        if failed is not None:
            failed.attempts += 1
            failed.status = "failed"
            failed.error_message = str(exc)[:2000]
            db.commit()
        raise
