from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConnectionType = Literal["api", "webhook", "file"]
IntegrationStatus = Literal["inactive", "connected", "error"]


class POSIntegrationCreate(BaseModel):
    location_id: int
    provider: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    connection_type: ConnectionType = "api"
    base_url: str | None = Field(default=None, max_length=500)
    external_account_id: str | None = Field(default=None, max_length=200)
    credentials_ref: str | None = Field(default=None, max_length=500)
    config: dict | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=1440)


class POSIntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    connection_type: ConnectionType | None = None
    base_url: str | None = Field(default=None, max_length=500)
    external_account_id: str | None = Field(default=None, max_length=200)
    credentials_ref: str | None = Field(default=None, max_length=500)
    config: dict | None = None
    active: bool | None = None
    status: IntegrationStatus | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=1440)


class WebhookTokenResponse(BaseModel):
    integration_id: int
    webhook_token: str
    note: str = "Store this token now; it cannot be shown again."


class POSIntegrationRead(BaseModel):
    id: int
    company_id: int
    location_id: int
    provider: str
    name: str
    connection_type: ConnectionType
    status: IntegrationStatus
    base_url: str | None
    external_account_id: str | None
    credentials_ref: str | None
    config: dict | None
    webhook_configured: bool = False
    sync_interval_minutes: int | None = None
    next_sync_at: datetime | None = None
    consecutive_failures: int = 0
    sync_paused_reason: str | None = None
    last_sync_cursor: str | None
    last_synced_at: datetime | None
    active: bool

    model_config = ConfigDict(from_attributes=True)


class ConnectionTestResult(BaseModel):
    integration_id: int
    provider: str
    success: bool
    message: str



class POSSyncResult(BaseModel):
    integration_id: int
    provider: str
    fetched: int
    imported: int
    skipped_duplicates: int
