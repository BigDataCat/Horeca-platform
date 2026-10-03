from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CanonicalSaleLine(BaseModel):
    external_product_id: str | None = None
    product_name: str = Field(min_length=1, max_length=300)
    quantity: Decimal = Field(gt=0)
    uom: str = Field(min_length=1, max_length=20)
    unit_price: Decimal
    net_value: Decimal
    tax_value: Decimal = Decimal("0")


class CanonicalSale(BaseModel):
    external_id: str = Field(min_length=1, max_length=200)
    occurred_at: datetime
    currency: str = Field(min_length=3, max_length=3)
    net_value: Decimal
    tax_value: Decimal = Decimal("0")
    gross_value: Decimal
    lines: list[CanonicalSaleLine] = Field(min_length=1)


class SalesImportRequest(BaseModel):
    integration_id: int
    sales: list[CanonicalSale] = Field(min_length=1)


class SalesImportResult(BaseModel):
    imported: int
    skipped_duplicates: int
