from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product_cost import ProductCost


def resolve_unit_cost(
    db: Session,
    company_id: int,
    product_id: int,
    location_id: int | None,
    at: datetime | None = None,
) -> ProductCost | None:
    """Latest cost effective at ``at``.

    With a location: that location's cost, else the company-wide cost. Without a location
    (company-wide view): the company-wide cost, else the most recently recorded cost of any
    location (e.g. from a goods receipt), so single-site companies get a cost without extra setup.
    """
    at = at or datetime.now(timezone.utc)

    def latest(location_filter) -> ProductCost | None:
        return db.scalar(
            select(ProductCost)
            .where(
                ProductCost.company_id == company_id,
                ProductCost.product_id == product_id,
                ProductCost.effective_from <= at,
                location_filter,
            )
            .order_by(ProductCost.effective_from.desc(), ProductCost.id.desc())
            .limit(1)
        )

    if location_id is not None:
        cost = latest(ProductCost.location_id == location_id)
        if cost is not None:
            return cost

    cost = latest(ProductCost.location_id.is_(None))
    if cost is None and location_id is None:
        cost = latest(ProductCost.location_id.is_not(None))
    return cost
