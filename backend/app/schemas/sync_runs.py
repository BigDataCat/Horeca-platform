from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SyncRunRead(BaseModel):
    id: int
    integration_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    fetched: int
    imported: int
    skipped_duplicates: int
    error_message: str | None
    trigger: str = "manual"

    model_config = ConfigDict(from_attributes=True)
