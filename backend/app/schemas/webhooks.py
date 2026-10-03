from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sales import CanonicalSale


class POSWebhookRequest(BaseModel):
    event_type: str = Field(default="sale.created", min_length=1, max_length=100)
    event_id: str = Field(min_length=1, max_length=200)
    sale: CanonicalSale


class POSWebhookResponse(BaseModel):
    event_id: str
    accepted: bool
    duplicate: bool
    message: str


class WebhookEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    integration_id: int
    external_event_id: str
    event_type: str
    received_at: datetime
    status: str
    attempts: int
    error_message: str | None
    processed_at: datetime | None
