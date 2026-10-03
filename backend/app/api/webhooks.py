import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.pos_integration import POSIntegration
from app.models.sale import Sale
from app.models.webhook_event import WebhookEvent
from app.schemas.webhooks import POSWebhookRequest, POSWebhookResponse
from app.services.sales_ingestion import import_sale

router = APIRouter(prefix="/integrations/pos", tags=["pos-webhooks"])


@router.post("/{integration_id}/webhook", response_model=POSWebhookResponse)
def receive_webhook(
    integration_id: int,
    payload: POSWebhookRequest,
    x_webhook_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> POSWebhookResponse:
    integration = db.get(POSIntegration, integration_id)
    if integration is None or not integration.active:
        raise HTTPException(status_code=404, detail="POS integration not found")

    configured_token = None
    if integration.config:
        configured_token = integration.config.get("webhook_token")

    if not configured_token or not x_webhook_token or not hmac.compare_digest(
        str(configured_token), x_webhook_token
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token")

    existing = db.scalar(
        select(WebhookEvent).where(
            WebhookEvent.integration_id == integration_id,
            WebhookEvent.external_event_id == payload.event_id,
        )
    )
    if existing is not None:
        return POSWebhookResponse(
            event_id=payload.event_id,
            accepted=True,
            duplicate=True,
            message="Webhook event was already processed.",
        )

    event = WebhookEvent(
        company_id=integration.company_id,
        integration_id=integration.id,
        external_event_id=payload.event_id,
        event_type=payload.event_type,
        received_at=datetime.now(timezone.utc),
        status="received",
    )
    db.add(event)

    try:
        imported = import_sale(db, integration, payload.sale)
        event.status = "processed" if imported else "duplicate_sale"
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Webhook event was already received")
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Webhook processing failed: {exc}")

    return POSWebhookResponse(
        event_id=payload.event_id,
        accepted=True,
        duplicate=not imported,
        message="Webhook processed successfully." if imported else "Sale was already imported.",
    )
