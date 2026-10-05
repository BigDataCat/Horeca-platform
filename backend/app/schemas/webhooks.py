from datetime import datetime

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sales import CanonicalSale


class RefundedLine(BaseModel):
    external_product_id: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)


class POSWebhookRequest(BaseModel):
    """``event_type`` is sale.created, sale.cancelled, sale.refunded or sale.partially_refunded.
    A partial refund lists the refunded lines (matched to the sale's lines by external product id)."""

    event_type: str = Field(default="sale.created", min_length=1, max_length=100)
    event_id: str = Field(min_length=1, max_length=200)
    sale: CanonicalSale
    refunded_lines: list[RefundedLine] | None = None


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
