"""Automatic audit trail.

Authenticated requests set ``db.info["actor"]``; every create/update/delete of a tracked model
made through that session is then recorded in ``audit_logs`` in the same transaction.
Background jobs and webhooks have no actor and are not audited here (they have their own
SyncRun / WebhookEvent history).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.company import Company
from app.models.invoice import InvoiceImport
from app.models.location import Location
from app.models.pos_integration import POSIntegration
from app.models.product import Product
from app.models.product_cost import ProductCost
from app.models.product_mapping import ProductMapping
from app.models.product_uom_conversion import ProductUOMConversion
from app.models.purchasing import GoodsReceipt, Supplier
from app.models.recipe import Recipe
from app.models.sale import Sale
from app.models.stock_ops import ProductionOrder, StockCount, StockTransfer
from app.models.user import User

TRACKED = {
    Company: "company",
    Location: "location",
    User: "user",
    Product: "product",
    ProductCost: "product_cost",
    ProductMapping: "product_mapping",
    ProductUOMConversion: "uom_conversion",
    Recipe: "recipe",
    POSIntegration: "pos_integration",
    Supplier: "supplier",
    InvoiceImport: "invoice_import",
    GoodsReceipt: "goods_receipt",
    StockCount: "stock_count",
    StockTransfer: "stock_transfer",
    ProductionOrder: "production_order",
}
# Sales are imported in bulk; only manual status changes (cancel/refund) are interesting.
UPDATE_ONLY = {Sale: "sale"}

SENSITIVE = {"password_hash", "webhook_token_hash", "token_version", "source_payload", "credentials_ref", "content", "extracted", "invoice_inbox_token"}
VOLATILE = {
    "created_at",
    "updated_at",
    "last_sync_cursor",
    "last_synced_at",
    "next_sync_at",
    "consecutive_failures",
    "sync_paused_reason",
    "status_changed_at",
}
IGNORED = SENSITIVE | VOLATILE
# Connection health flips on every sync/test; user-driven changes are in the other fields.
IGNORED_BY_MODEL = {POSIntegration: {"status"}}


def _ignored(obj) -> set[str]:
    extra = set()
    for model, fields in IGNORED_BY_MODEL.items():
        if isinstance(obj, model):
            extra |= fields
    return IGNORED | extra


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {"keys": sorted(str(k) for k in value)}  # never log config values (may hold secrets)
    return str(value)


def _entity_type(obj) -> tuple[str | None, bool]:
    for model, name in TRACKED.items():
        if isinstance(obj, model):
            return name, False
    for model, name in UPDATE_ONLY.items():
        if isinstance(obj, model):
            return name, True
    return None, False


def _company_id(obj) -> int | None:
    return obj.id if isinstance(obj, Company) else getattr(obj, "company_id", None)


def _snapshot(obj) -> dict:
    mapper = inspect(obj).mapper
    return {
        column.key: _plain(getattr(obj, column.key, None))
        for column in mapper.column_attrs
        if column.key not in _ignored(obj) and column.key != "id"
    }


def _changes(obj) -> dict:
    changes = {}
    for attr in inspect(obj).mapper.column_attrs:
        if attr.key in _ignored(obj):
            continue
        history = inspect(obj).attrs[attr.key].history
        if history.has_changes():
            old = history.deleted[0] if history.deleted else None
            new = history.added[0] if history.added else None
            if old != new:
                changes[attr.key] = [_plain(old), _plain(new)]
    return changes


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _context) -> None:
    actor = session.info.get("actor")
    if not actor:
        return
    pending = session.info.setdefault("audit_pending", [])

    for obj in session.new:
        name, update_only = _entity_type(obj)
        if name and not update_only and _company_id(obj) == actor["company_id"]:
            pending.append((actor, "created", name, obj, _snapshot(obj)))
    for obj in session.dirty:
        name, _ = _entity_type(obj)
        if name and _company_id(obj) == actor["company_id"] and session.is_modified(obj):
            changes = _changes(obj)
            if changes:
                pending.append((actor, "updated", name, obj, changes))
    for obj in session.deleted:
        name, update_only = _entity_type(obj)
        if name and not update_only and _company_id(obj) == actor["company_id"]:
            pending.append((actor, "deleted", name, obj, {"id": getattr(obj, "id", None)}))


@event.listens_for(Session, "after_flush_postexec")
def _write(session: Session, _context) -> None:
    pending = session.info.pop("audit_pending", None)
    if not pending:
        return
    for actor, action, name, obj, details in pending:
        session.add(
            AuditLog(
                company_id=actor["company_id"],
                user_id=actor["user_id"],
                action=action,
                entity_type=name,
                entity_id=getattr(obj, "id", None),
                details=details,
            )
        )
