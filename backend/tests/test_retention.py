from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.audit_log import AuditLog
from app.models.webhook_event import WebhookEvent
from app.services.retention import purge_expired_data
from tests.conftest import create_integration, create_location, create_product


def test_audit_entries_older_than_retention_are_purged(client, tenant_a):
    create_product(client, tenant_a, "Old")
    create_product(client, tenant_a, "New")
    with SessionLocal() as db:
        oldest = db.query(AuditLog).order_by(AuditLog.id).first()
        oldest_id = oldest.id
        oldest.created_at = datetime.now(timezone.utc) - timedelta(days=400)
        db.commit()
        removed = purge_expired_data(db, audit_days=365)
        assert removed["audit_logs"] >= 1
        assert db.get(AuditLog, oldest_id) is None
        assert db.query(AuditLog).count() >= 1  # recent entries stay


def test_audit_log_kept_forever_by_default(client, tenant_a):
    create_product(client, tenant_a, "Old")
    with SessionLocal() as db:
        for entry in db.query(AuditLog):
            entry.created_at = datetime.now(timezone.utc) - timedelta(days=5000)
        db.commit()
        before = db.query(AuditLog).count()
        assert purge_expired_data(db, audit_days=None)["audit_logs"] == 0
        assert db.query(AuditLog).count() == before


def test_only_finished_webhook_events_are_purged(client, tenant_a):
    location = create_location(client, tenant_a)
    integration = create_integration(client, tenant_a, location, provider="mock")
    old = datetime.now(timezone.utc) - timedelta(days=200)
    with SessionLocal() as db:
        for index, status in enumerate(["processed", "duplicate_sale", "failed", "received"]):
            db.add(
                WebhookEvent(
                    company_id=tenant_a["company_id"], integration_id=integration["id"],
                    external_event_id=f"E{index}", event_type="sale.created", received_at=old, status=status,
                )
            )
        db.commit()
        removed = purge_expired_data(db, audit_days=None, webhook_event_days=90)
        assert removed["webhook_events"] == 2
        assert sorted(e.status for e in db.query(WebhookEvent)) == ["failed", "received"]
