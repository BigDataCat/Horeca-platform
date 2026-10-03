from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.location import Location


class POSIntegration(TimestampMixin, Base):
    __tablename__ = "pos_integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    connection_type: Mapped[str] = mapped_column(String(30), nullable=False, default="api")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="inactive")
    base_url: Mapped[str | None] = mapped_column(String(500))
    external_account_id: Mapped[str | None] = mapped_column(String(200))
    credentials_ref: Mapped[str | None] = mapped_column(String(500))
    config: Mapped[dict | None] = mapped_column(JSON)
    webhook_token_hash: Mapped[str | None] = mapped_column(String(64))
    sync_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sync_paused_reason: Mapped[str | None] = mapped_column(String(500))
    last_sync_cursor: Mapped[str | None] = mapped_column(String(500))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def webhook_configured(self) -> bool:
        return self.webhook_token_hash is not None

    company: Mapped["Company"] = relationship()
    location: Mapped["Location"] = relationship()
