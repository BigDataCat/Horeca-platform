from pydantic import BaseModel, Field

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
