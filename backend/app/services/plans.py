from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.location import Location
from app.models.pos_integration import POSIntegration
from app.models.sale import Sale
from app.models.user import User


@dataclass(frozen=True)
class Plan:
    name: str
    max_locations: int | None
    max_users: int | None
    max_integrations: int | None


PLANS: dict[str, Plan] = {
    "trial": Plan("trial", 1, 3, 1),
    "starter": Plan("starter", 3, 10, 3),
    "business": Plan("business", 10, 50, 20),
    "unlimited": Plan("unlimited", None, None, None),
}


def get_plan(name: str) -> Plan:
    return PLANS.get(name, PLANS["trial"])


def usage(db: Session, company_id: int) -> dict[str, int]:
    def count(model, *conditions):
        return db.scalar(select(func.count(model.id)).where(model.company_id == company_id, *conditions)) or 0

    return {
        "locations": count(Location, Location.active.is_(True)),
        "users": count(User, User.active.is_(True)),
        "integrations": count(POSIntegration, POSIntegration.active.is_(True)),
        "sales": count(Sale),
    }


_LIMIT_FIELD = {"locations": "max_locations", "users": "max_users", "integrations": "max_integrations"}


def enforce_limit(db: Session, company_id: int, resource: str) -> None:
    """Raise 402 when creating one more ``resource`` would exceed the company's plan."""
    company = db.get(Company, company_id)
    plan = get_plan(company.plan if company else "trial")
    limit = getattr(plan, _LIMIT_FIELD[resource])
    if limit is not None and usage(db, company_id)[resource] >= limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Your {plan.name} plan allows at most {limit} active {resource}. Upgrade the plan to add more.",
        )
