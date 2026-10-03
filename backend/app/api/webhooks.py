import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.pos_integration import POSIntegration
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.schemas.webhooks import POSWebhookRequest, POSWebhookResponse, WebhookEventRead
from app.services.webhook_processing import process_webhook_event

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

    if (
        not integration.webhook_token_hash
        or not x_webhook_token
        or not hmac.compare_digest(
            integration.webhook_token_hash, hashlib.sha256(x_webhook_token.encode()).hexdigest()
        )
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token")

    existing = db.scalar(
        select(WebhookEvent).where(
            WebhookEvent.integration_id == integration_id,
            WebhookEvent.external_event_id == payload.event_id,
        )
    )
    if existing is not None and existing.status != "failed":
        return POSWebhookResponse(
            event_id=payload.event_id,
            accepted=True,
            duplicate=True,
            message="Webhook event was already processed.",
        )

    event = existing
    if event is None:
        event = WebhookEvent(
            company_id=integration.company_id,
            integration_id=integration.id,
            external_event_id=payload.event_id,
            event_type=payload.event_type,
            received_at=datetime.now(timezone.utc),
            status="received",
        )
        db.add(event)
    # A redelivery of a failed event replaces the stored payload and is retried.
    event.payload = payload.model_dump_json()

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Webhook event was already received")

    try:
        imported = process_webhook_event(db, integration, event)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Webhook processing failed: {exc}")

    return POSWebhookResponse(
        event_id=payload.event_id,
        accepted=True,
        duplicate=not imported,
        message="Webhook processed successfully." if imported else "Sale was already imported.",
    )


def _require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=403, detail="Owner or manager role required")


def _own_integration(db: Session, user: User, integration_id: int) -> POSIntegration:
    integration = db.get(POSIntegration, integration_id)
    if integration is None or integration.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="POS integration not found")
    return integration


@router.get("/{integration_id}/webhook-events", response_model=list[WebhookEventRead])
def list_webhook_events(
    integration_id: int,
    status_filter: str | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WebhookEvent]:
    _own_integration(db, current_user, integration_id)
    query = select(WebhookEvent).where(
        WebhookEvent.company_id == current_user.company_id,
        WebhookEvent.integration_id == integration_id,
    )
    if status_filter:
        query = query.where(WebhookEvent.status == status_filter)
    return list(db.scalars(query.order_by(WebhookEvent.id.desc()).limit(min(max(limit, 1), 500))).all())


@router.post("/{integration_id}/webhook-events/{event_id}/replay", response_model=WebhookEventRead)
def replay_webhook_event(
    integration_id: int,
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WebhookEvent:
    _require_manager(current_user)
    integration = _own_integration(db, current_user, integration_id)
    event = db.get(WebhookEvent, event_id)
    if event is None or event.integration_id != integration.id or event.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Webhook event not found")
    if event.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed events can be replayed")

    try:
        process_webhook_event(db, integration, event)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Replay failed: {exc}")

    db.refresh(event)
    return event
