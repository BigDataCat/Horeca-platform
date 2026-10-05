from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.sales_ingestion import ACTIVE_STATUSES
from app.models.product import Product
from app.models.recipe import Recipe
from app.models.sale import Sale, SaleLine
from app.services.costing import resolve_unit_cost
from app.services.sales_ingestion import normalize_quantity


def recipe_unit_cost(db: Session, company_id: int, product_id: int, location_id: int) -> Decimal | None:
    """Cost of one unit of ``product_id`` from its recipe at ``location_id`` (None if unknown).

    The location recipe wins over the company-wide one; any ingredient without a known cost or
    without an explicit UOM conversion makes the whole cost unknown instead of guessing.
    """
    recipe = None
    for location_filter in (Recipe.location_id == location_id, Recipe.location_id.is_(None)):
        recipe = db.scalar(
            select(Recipe).where(
                Recipe.company_id == company_id,
                Recipe.product_id == product_id,
                Recipe.active.is_(True),
                location_filter,
            )
        )
        if recipe is not None:
            break
    if recipe is None:
        return None

    total = Decimal("0")
    for line in recipe.lines:
        ingredient = line.ingredient_product
        quantity, uom = normalize_quantity(db, company_id, ingredient, line.quantity, line.uom)
        if uom != ingredient.base_uom.upper():
            return None
        cost = resolve_unit_cost(db, company_id, ingredient.id, location_id)
        if cost is None:
            return None
        total += quantity * (Decimal("1") + line.waste_factor) * cost.unit_cost
    return total


def margin_report(
    db: Session,
    company_id: int,
    location_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict]:
    query = (
        select(
            SaleLine.product_id,
            Sale.location_id,
            func.sum(SaleLine.quantity - SaleLine.refunded_quantity).label("quantity"),
            func.sum(SaleLine.net_value - SaleLine.refunded_net_value).label("revenue"),
        )
        .join(Sale, Sale.id == SaleLine.sale_id)
        .where(
            Sale.company_id == company_id,
            Sale.status.in_(ACTIVE_STATUSES),
            SaleLine.product_id.is_not(None),
        )
        .group_by(SaleLine.product_id, Sale.location_id)
    )
    if location_id is not None:
        query = query.where(Sale.location_id == location_id)
    if date_from is not None:
        query = query.where(Sale.occurred_at >= date_from)
    if date_to is not None:
        query = query.where(Sale.occurred_at < date_to)

    products: dict[int, dict] = {}
    for row in db.execute(query).all():
        entry = products.setdefault(
            row.product_id,
            {"quantity": Decimal("0"), "revenue": Decimal("0"), "cost": Decimal("0"), "cost_known": True},
        )
        entry["quantity"] += row.quantity
        entry["revenue"] += row.revenue
        unit_cost = recipe_unit_cost(db, company_id, row.product_id, row.location_id)
        if unit_cost is None:
            entry["cost_known"] = False
        else:
            entry["cost"] += unit_cost * row.quantity

    names = {
        p.id: p.name
        for p in db.scalars(select(Product).where(Product.company_id == company_id, Product.id.in_(products.keys()))).all()
    } if products else {}

    result = []
    for product_id, entry in sorted(products.items(), key=lambda item: names.get(item[0], "")):
        known = entry["cost_known"]
        revenue = entry["revenue"]
        result.append(
            {
                "product_id": product_id,
                "product_name": names.get(product_id, ""),
                "quantity_sold": entry["quantity"],
                "revenue": revenue,
                "cost": entry["cost"] if known else None,
                "margin": revenue - entry["cost"] if known else None,
                "food_cost_pct": (entry["cost"] / revenue * 100) if known and revenue else None,
            }
        )
    return result
