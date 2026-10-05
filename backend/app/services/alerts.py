from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.sales_ingestion import ACTIVE_STATUSES
from app.models.inventory import ProductStock
from app.models.pos_integration import POSIntegration
from app.models.product import Product
from app.models.recipe import Recipe, RecipeLine
from app.models.sale import Sale, SaleLine
from app.models.webhook_event import WebhookEvent
from app.services.costing import resolve_unit_cost

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def compute_alerts(db: Session, company_id: int) -> list[dict]:
    alerts: list[dict] = []

    def add(kind: str, severity: str, message: str, entity_type: str | None = None, entity_id: int | None = None):
        alerts.append(
            {"type": kind, "severity": severity, "message": message, "entity_type": entity_type, "entity_id": entity_id}
        )

    # Stock levels
    rows = db.execute(
        select(ProductStock, Product)
        .join(Product, Product.id == ProductStock.product_id)
        .where(ProductStock.company_id == company_id, Product.active.is_(True))
    ).all()
    for stock, product in rows:
        if stock.quantity < 0:
            add("negative_stock", "critical", f"{product.name} has negative stock ({stock.quantity} {stock.uom}) at location {stock.location_id}", "product", product.id)
        elif product.reorder_level is not None and stock.quantity <= product.reorder_level:
            add("low_stock", "warning", f"{product.name} is at or below its reorder level ({stock.quantity} {stock.uom} <= {product.reorder_level}) at location {stock.location_id}", "product", product.id)

    # Integrations
    now = datetime.now(timezone.utc)
    for integration in db.scalars(
        select(POSIntegration).where(POSIntegration.company_id == company_id, POSIntegration.active.is_(True))
    ).all():
        if integration.sync_paused_reason:
            add("sync_paused", "critical", f"{integration.name}: automatic sync paused. {integration.sync_paused_reason}", "pos_integration", integration.id)
        elif integration.status == "error":
            add("sync_failed", "warning", f"{integration.name}: last sync failed", "pos_integration", integration.id)
        elif (
            integration.sync_interval_minutes
            and integration.last_synced_at is not None
            and now - integration.last_synced_at > timedelta(minutes=3 * integration.sync_interval_minutes)
        ):
            add("sync_stale", "warning", f"{integration.name}: no successful sync for over three intervals", "pos_integration", integration.id)

    failed_webhooks = db.scalar(
        select(func.count(WebhookEvent.id)).where(WebhookEvent.company_id == company_id, WebhookEvent.status == "failed")
    ) or 0
    if failed_webhooks:
        add("webhook_failed", "warning", f"{failed_webhooks} webhook event(s) failed and can be replayed")

    # Mapping gaps
    unmatched = db.scalar(
        select(func.count(func.distinct(SaleLine.external_product_id)))
        .join(Sale, Sale.id == SaleLine.sale_id)
        .where(
            Sale.company_id == company_id,
            Sale.status.in_(ACTIVE_STATUSES),
            SaleLine.product_id.is_(None),
            SaleLine.external_product_id.is_not(None),
        )
    ) or 0
    if unmatched:
        add("unmatched_products", "info", f"{unmatched} POS product(s) are not mapped to a product")

    # Costing gaps: recipe ingredients with no resolvable cost
    seen: set[tuple[int, int | None]] = set()
    for recipe, line in db.execute(
        select(Recipe, RecipeLine)
        .join(RecipeLine, RecipeLine.recipe_id == Recipe.id)
        .where(Recipe.company_id == company_id, Recipe.active.is_(True))
    ).all():
        key = (line.ingredient_product_id, recipe.location_id)
        if key in seen:
            continue
        seen.add(key)
        if resolve_unit_cost(db, company_id, line.ingredient_product_id, recipe.location_id) is None:
            ingredient = line.ingredient_product
            add("missing_cost", "warning", f"No cost for ingredient {ingredient.name} used in recipe {recipe.name}", "product", ingredient.id)

    alerts.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], a["type"]))
    return alerts
