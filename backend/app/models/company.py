from typing import TYPE_CHECKING
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.location import Location
    from app.models.user import User

class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_identifier: Mapped[str | None] = mapped_column(String(50), unique=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_alert_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    plan: Mapped[str] = mapped_column(String(30), nullable=False, default="business", server_default="business")
    locations: Mapped[list["Location"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="company", cascade="all, delete-orphan")
