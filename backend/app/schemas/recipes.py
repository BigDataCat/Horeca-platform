from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RecipeLineCreate(BaseModel):
    ingredient_product_id: int
    quantity: Decimal = Field(gt=0)
    uom: str = Field(min_length=1, max_length=20)
    waste_factor: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class RecipeCreate(BaseModel):
    product_id: int
    location_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    lines: list[RecipeLineCreate] = Field(min_length=1)


class RecipeLineRead(BaseModel):
    id: int
    ingredient_product_id: int
    quantity: Decimal
    uom: str
    waste_factor: Decimal
    model_config = ConfigDict(from_attributes=True)


class RecipeRead(BaseModel):
    id: int
    product_id: int
    location_id: int | None
    name: str
    active: bool
    lines: list[RecipeLineRead]
    model_config = ConfigDict(from_attributes=True)
