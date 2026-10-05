from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtractedLine(BaseModel):
    description: str
    product_code: str | None = None
    quantity: Decimal
    unit: str | None = None
    unit_price: Decimal | None = None  # net (VAT excluded) price per unit
    line_net: Decimal | None = None
    vat_rate: Decimal | None = None


class ExtractedInvoice(BaseModel):
    document_type: Literal["invoice", "credit_note"] = "invoice"
    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    document_number: str | None = None
    issue_date: date | None = None
    currency: str | None = None
    lines: list[ExtractedLine] = []
    total_net: Decimal | None = None
    total_vat: Decimal | None = None
    total_gross: Decimal | None = None


class InvoiceLinePatch(BaseModel):
    index: int = Field(ge=0)
    product_id: int | None = None
    skip: bool | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    unit_price: Decimal | None = Field(default=None, ge=0)
    clear_product: bool = False


class InvoicePatch(BaseModel):
    location_id: int | None = None
    supplier_id: int | None = None
    document_number: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    lines: list[InvoiceLinePatch] = []


class InvoicePost(BaseModel):
    location_id: int | None = None


class InvoiceImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_id: int | None
    supplier_id: int | None
    source: str
    source_type: str
    filename: str | None
    status: str
    extracted: dict | None
    warnings: list | None
    error: str | None
    receipt_id: int | None
    created_at: datetime
    posted_at: datetime | None
    blocking: list[str] = []


class InboxInfo(BaseModel):
    address: str | None
    configured: bool
    auto_post: bool
    default_location_id: int | None
    note: str


class InboxSettings(BaseModel):
    auto_post: bool | None = None
    default_location_id: int | None = None
