from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.company import Company


class ProductUOMConversion(TimestampMixin, Base):
    __tablename__ = "product_uom_conversions"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "from_uom",
            "to_uom",
            name="uq_product_uom_conversion",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    to_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    factor: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped["Company"] = relationship()
    product: Mapped["Product"] = relationship()
