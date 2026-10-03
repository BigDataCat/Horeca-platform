from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.pos_integration import POSIntegration
    from app.models.product import Product
    from app.models.company import Company


class ProductMapping(TimestampMixin, Base):
    __tablename__ = "product_mappings"
    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "external_product_id",
            name="uq_product_mapping_integration_external",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("pos_integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    external_product_name: Mapped[str | None] = mapped_column(String(300))
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_method: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped["Company"] = relationship()
    integration: Mapped["POSIntegration"] = relationship()
    product: Mapped["Product"] = relationship()
