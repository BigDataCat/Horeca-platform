from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _valid_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError("Unknown time zone; use an IANA name such as Europe/Bucharest")
    return value



class LocationBase(BaseModel):
    company_id: int
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    country: str = Field(default="RO", min_length=2, max_length=2)
    timezone: str = Field(default="Europe/Bucharest", max_length=64)

    _check_timezone = field_validator("timezone")(_valid_timezone)


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    active: bool | None = None

    _check_timezone = field_validator("timezone")(_valid_timezone)


class LocationRead(LocationBase):
    id: int
    active: bool

    model_config = ConfigDict(from_attributes=True)
