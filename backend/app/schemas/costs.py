from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ConfigDict


class ProductCostCreate(BaseModel):
    product_id: int
    location_id: int | None = None
    unit_cost: Decimal = Field(gt=0)
    currency: str = Field(default="RON", min_length=3, max_length=3)
    effective_from: datetime


class ProductCostRead(BaseModel):
    id: int
    product_id: int
    location_id: int | None
    unit_cost: Decimal
    currency: str
    effective_from: datetime
    model_config = ConfigDict(from_attributes=True)


class RecipeCostLineRead(BaseModel):
    ingredient_product_id: int
    quantity: Decimal
    uom: str
    unit_cost: Decimal | None
    line_cost: Decimal | None


class RecipeCostRead(BaseModel):
    recipe_id: int
    recipe_name: str
    currency: str
    total_cost: Decimal | None
    lines: list[RecipeCostLineRead]
