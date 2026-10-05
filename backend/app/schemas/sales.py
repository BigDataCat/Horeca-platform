from datetime import datetime
from decimal import Decimal
from typing import Literal

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


class UnmatchedProductRead(BaseModel):
    integration_id: int
    external_product_id: str
    product_name: str
    uom: str
    occurrences: int
    total_quantity: Decimal


class SaleLineRead(BaseModel):
    id: int
    product_id: int | None
    external_product_id: str | None
    product_name: str
    quantity: Decimal
    uom: str
    unit_price: Decimal
    net_value: Decimal
    tax_value: Decimal
    refunded_quantity: Decimal = Decimal("0")
    refunded_net_value: Decimal = Decimal("0")

    model_config = {"from_attributes": True}


class SaleRead(BaseModel):
    id: int
    company_id: int
    location_id: int
    integration_id: int | None
    external_id: str
    occurred_at: datetime
    currency: str
    net_value: Decimal
    tax_value: Decimal
    gross_value: Decimal
    status: str
    status_reason: str | None = None
    refunded_net_value: Decimal = Decimal("0")
    refunded_tax_value: Decimal = Decimal("0")
    lines: list[SaleLineRead]

    model_config = {"from_attributes": True}


class SaleStatusChange(BaseModel):
    status: Literal["cancelled", "refunded"]
    reason: str | None = Field(default=None, max_length=500)


class RefundLine(BaseModel):
    line_id: int
    quantity: Decimal = Field(gt=0)


class SaleRefundRequest(BaseModel):
    lines: list[RefundLine] = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=500)
