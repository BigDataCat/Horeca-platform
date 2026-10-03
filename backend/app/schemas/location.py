from pydantic import BaseModel, ConfigDict, Field


class LocationBase(BaseModel):
    company_id: int
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    country: str = Field(default="RO", min_length=2, max_length=2)


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    active: bool | None = None


class LocationRead(LocationBase):
    id: int
    active: bool

    model_config = ConfigDict(from_attributes=True)
