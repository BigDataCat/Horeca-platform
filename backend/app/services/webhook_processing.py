import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.pos_integration import POSIntegration
from app.models.webhook_event import WebhookEvent
from app.schemas.sales import CanonicalSale
from decimal import Decimal

from sqlalchemy import select

from app.models.sale import Sale
from app.services.sales_ingestion import RefundError, apply_sale_status_event, import_sale, refund_sale_lines

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
        if event.event_type == "sale.partially_refunded":
            imported = _partial_refund(db, integration, sale, json.loads(event.payload or "{}").get("refunded_lines") or [])
        elif new_status is not None:
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


def _partial_refund(db: Session, integration: POSIntegration, canonical: CanonicalSale, refunded_lines: list[dict]) -> bool:
    """Apply a partial refund event. Returns False when there is nothing left to refund (replayed event).

    The sale must already exist; if it does not, the event fails and can be replayed after the sale arrives."""
    if not refunded_lines:
        raise ValueError("sale.partially_refunded needs refunded_lines")
    sale = db.scalar(
        select(Sale).where(
            Sale.company_id == integration.company_id,
            Sale.integration_id == integration.id,
            Sale.external_id == canonical.external_id,
        )
    )
    if sale is None:
        raise ValueError(f"Sale {canonical.external_id} has not been received yet; replay this event after it arrives")

    remaining = {line.id: line.quantity - line.refunded_quantity for line in sale.lines}
    requests: list[tuple[int, Decimal]] = []
    for item in refunded_lines:
        wanted = Decimal(str(item["quantity"]))
        for line in sale.lines:
            if line.external_product_id != item["external_product_id"] or wanted <= 0:
                continue
            take = min(wanted, remaining[line.id])
            if take > 0:
                requests.append((line.id, take))
                remaining[line.id] -= take
                wanted -= take
        if wanted > 0:
            raise ValueError(f"Cannot refund {item['quantity']} of {item['external_product_id']}: not enough unrefunded quantity")
    try:
        refund_sale_lines(db, sale, _merge(requests), "POS partial refund")
    except RefundError as exc:
        if "already" in str(exc):
            return False
        raise ValueError(str(exc))
    return True


def _merge(requests: list[tuple[int, Decimal]]) -> list[tuple[int, Decimal]]:
    merged: dict[int, Decimal] = {}
    for line_id, quantity in requests:
        merged[line_id] = merged.get(line_id, Decimal("0")) + quantity
    return list(merged.items())
