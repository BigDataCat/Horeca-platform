from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ConfigDict


class StockRead(BaseModel):
    id: int
    location_id: int
    product_id: int
    quantity: Decimal
    uom: str
    model_config = ConfigDict(from_attributes=True)


class StockAdjustmentCreate(BaseModel):
    location_id: int
    product_id: int
    quantity: Decimal
    uom: str = Field(min_length=1, max_length=20)
    movement_type: str = Field(default="adjustment", min_length=1, max_length=30)
    note: str | None = Field(default=None, max_length=500)


class StockMovementRead(BaseModel):
    id: int
    location_id: int
    product_id: int
    movement_type: str
    quantity: Decimal
    uom: str
    reference_type: str | None
    reference_id: str | None
    occurred_at: datetime
    note: str | None
    model_config = ConfigDict(from_attributes=True)
