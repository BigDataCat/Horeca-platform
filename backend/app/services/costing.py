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
    """Latest cost effective at ``at``: the location-specific one, else the global one."""
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

    return latest(ProductCost.location_id.is_(None))
