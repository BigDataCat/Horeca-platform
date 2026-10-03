from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=150)
    base_uom: str = Field(default="EA", min_length=1, max_length=20)


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=150)
    base_uom: str | None = Field(default=None, min_length=1, max_length=20)
    active: bool | None = None


class ProductRead(BaseModel):
    id: int
    company_id: int
    sku: str | None
    name: str
    category: str | None
    base_uom: str
    active: bool

    model_config = ConfigDict(from_attributes=True)
