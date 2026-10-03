from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tax_identifier: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_identifier: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    active: bool | None = None


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tax_identifier: str | None
    email: str | None
    phone: str | None
    active: bool


class ReceiptLineCreate(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    uom: str = Field(min_length=1, max_length=20)
    unit_cost: Decimal = Field(gt=0, description="Cost per one `uom`")


class GoodsReceiptCreate(BaseModel):
    location_id: int
    supplier_id: int | None = None
    document_number: str | None = Field(default=None, max_length=100)
    received_at: datetime | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=500)
    lines: list[ReceiptLineCreate] = Field(min_length=1)


class ReceiptLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: Decimal
    uom: str
    unit_cost: Decimal


class GoodsReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_id: int
    supplier_id: int | None
    document_number: str | None
    received_at: datetime
    currency: str
    note: str | None
    lines: list[ReceiptLineRead]
