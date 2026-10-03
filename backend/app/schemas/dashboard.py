from decimal import Decimal

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    sales_count: int
    cancelled_sales: int = 0
    revenue: Decimal
    tax: Decimal
    gross_revenue: Decimal
    average_ticket: Decimal
    unmatched_products: int
    stock_items: int
    stock_value: Decimal
