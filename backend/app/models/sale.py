from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.location import Location
    from app.models.pos_integration import POSIntegration
    from app.models.product import Product


class Sale(TimestampMixin, Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id", name="uq_sales_integration_external_id"),
    )

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
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("pos_integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    net_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    gross_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source_payload: Mapped[str | None] = mapped_column(Text)

    location: Mapped["Location"] = relationship()
    integration: Mapped["POSIntegration | None"] = relationship()
    lines: Mapped[list["SaleLine"]] = relationship(
        back_populates="sale",
        cascade="all, delete-orphan",
    )


class SaleLine(Base):
    __tablename__ = "sale_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_product_id: Mapped[str | None] = mapped_column(String(200))
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    uom: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    net_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    sale: Mapped["Sale"] = relationship(back_populates="lines")
    product: Mapped["Product | None"] = relationship()
