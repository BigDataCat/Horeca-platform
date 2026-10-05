from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.password_reset import PasswordResetToken
from app.models.webhook_event import WebhookEvent


def purge_expired_data(db: Session, audit_days: int | None, webhook_event_days: int | None = 90, now: datetime | None = None) -> dict[str, int]:
    """Delete data past its retention period. ``None`` keeps that kind of data forever.

    - audit log entries older than ``audit_days``
    - processed/duplicate webhook events older than ``webhook_event_days`` (failed ones are kept until replayed)
    - used or expired password-reset/invite tokens older than a day"""
    now = now or datetime.now(timezone.utc)
    removed = {"audit_logs": 0, "webhook_events": 0, "reset_tokens": 0}
    if audit_days is not None:
        removed["audit_logs"] = db.execute(
            delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=audit_days))
        ).rowcount
    if webhook_event_days is not None:
        removed["webhook_events"] = db.execute(
            delete(WebhookEvent).where(
                WebhookEvent.status.in_(("processed", "duplicate_sale")),
                WebhookEvent.received_at < now - timedelta(days=webhook_event_days),
            )
        ).rowcount
    cutoff = now - timedelta(days=1)
    removed["reset_tokens"] = db.execute(
        delete(PasswordResetToken).where(
            (PasswordResetToken.expires_at < cutoff) | (PasswordResetToken.used_at < cutoff)
        )
    ).rowcount
    db.commit()
    return removed
