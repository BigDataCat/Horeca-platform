from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.reports import margin_report

router = APIRouter(prefix="/reports", tags=["reports"])


class MarginRow(BaseModel):
    product_id: int
    product_name: str
    quantity_sold: Decimal
    revenue: Decimal
    cost: Decimal | None
    margin: Decimal | None
    food_cost_pct: Decimal | None


@router.get("/margins", response_model=list[MarginRow])
def margins(
    location_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Per-product revenue, recipe cost, margin and food-cost % over completed sales.

    ``cost`` is null when the product has no recipe or an ingredient has no cost/conversion."""
    return margin_report(db, current_user.company_id, location_id, date_from, date_to)
