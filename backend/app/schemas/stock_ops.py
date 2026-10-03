from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CountLineCreate(BaseModel):
    product_id: int
    counted_quantity: Decimal = Field(ge=0)
    uom: str = Field(min_length=1, max_length=20)


class StockCountCreate(BaseModel):
    location_id: int
    counted_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    lines: list[CountLineCreate] = Field(min_length=1)


class CountLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    expected_quantity: Decimal
    counted_quantity: Decimal
    difference: Decimal
    uom: str


class StockCountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_id: int
    counted_at: datetime
    note: str | None
    lines: list[CountLineRead]


class TransferLineCreate(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    uom: str = Field(min_length=1, max_length=20)


class StockTransferCreate(BaseModel):
    from_location_id: int
    to_location_id: int
    transferred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    lines: list[TransferLineCreate] = Field(min_length=1)


class TransferLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: Decimal
    uom: str


class StockTransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_location_id: int
    to_location_id: int
    transferred_at: datetime
    note: str | None
    lines: list[TransferLineRead]
