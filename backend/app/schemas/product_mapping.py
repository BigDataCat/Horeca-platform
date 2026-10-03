from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductMappingCreate(BaseModel):
    integration_id: int
    external_product_id: str = Field(min_length=1, max_length=200)
    external_product_name: str | None = Field(default=None, max_length=300)
    product_id: int
    match_method: str = Field(default="manual", max_length=30)


class ProductMappingRead(BaseModel):
    id: int
    company_id: int
    integration_id: int
    external_product_id: str
    external_product_name: str | None
    product_id: int
    match_method: str
    confidence: Decimal
    active: bool

    model_config = ConfigDict(from_attributes=True)


class ProductUOMConversionCreate(BaseModel):
    product_id: int
    from_uom: str = Field(min_length=1, max_length=20)
    to_uom: str = Field(min_length=1, max_length=20)
    factor: Decimal = Field(gt=0)


class ProductUOMConversionRead(BaseModel):
    id: int
    company_id: int
    product_id: int
    from_uom: str
    to_uom: str
    factor: Decimal
    active: bool

    model_config = ConfigDict(from_attributes=True)
