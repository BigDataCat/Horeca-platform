from pydantic import BaseModel, ConfigDict, Field


class CompanyBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tax_identifier: str | None = Field(default=None, max_length=50)
    currency: str = Field(default="RON", min_length=3, max_length=3)


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_identifier: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    active: bool | None = None


class CompanyRead(CompanyBase):
    id: int
    active: bool

    model_config = ConfigDict(from_attributes=True)
