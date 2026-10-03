from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.inventory import ProductStock
from app.models.sale import Sale, SaleLine
from app.models.user import User
from app.schemas.dashboard import DashboardSummary
from app.services.costing import resolve_unit_cost

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardSummary:
    sales = db.execute(
        select(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.net_value), 0),
            func.coalesce(func.sum(Sale.tax_value), 0),
            func.coalesce(func.sum(Sale.gross_value), 0),
        ).where(Sale.company_id == current_user.company_id, Sale.status == "completed")
    ).one()

    cancelled_sales = int(
        db.scalar(
            select(func.count(Sale.id)).where(
                Sale.company_id == current_user.company_id, Sale.status != "completed"
            )
        )
        or 0
    )

    sales_count = int(sales[0] or 0)
    revenue = Decimal(str(sales[1] or 0))
    tax = Decimal(str(sales[2] or 0))
    gross_revenue = Decimal(str(sales[3] or 0))

    unmatched_products = int(
        db.scalar(
            select(func.count(func.distinct(SaleLine.external_product_id)))
            .join(Sale, Sale.id == SaleLine.sale_id)
            .where(
                Sale.company_id == current_user.company_id,
                Sale.status == "completed",
                SaleLine.product_id.is_(None),
                SaleLine.external_product_id.is_not(None),
            )
        )
        or 0
    )

    stock_items = int(
        db.scalar(
            select(func.count(ProductStock.id)).where(
                ProductStock.company_id == current_user.company_id
            )
        )
        or 0
    )

    stock_value = Decimal("0")
    for stock in db.scalars(
        select(ProductStock).where(ProductStock.company_id == current_user.company_id)
    ).all():
        cost = resolve_unit_cost(
            db, current_user.company_id, stock.product_id, stock.location_id
        )
        if cost is not None:
            stock_value += stock.quantity * cost.unit_cost

    average_ticket = (
        gross_revenue / sales_count if sales_count else Decimal("0")
    )

    return DashboardSummary(
        sales_count=sales_count,
        cancelled_sales=cancelled_sales,
        revenue=revenue,
        tax=tax,
        gross_revenue=gross_revenue,
        average_ticket=average_ticket,
        unmatched_products=unmatched_products,
        stock_items=stock_items,
        stock_value=stock_value,
    )
