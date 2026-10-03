from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.location import Location
    from app.models.product import Product


class Recipe(TimestampMixin, Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped["Company"] = relationship()
    product: Mapped["Product"] = relationship()
    location: Mapped["Location"] = relationship()
    lines: Mapped[list["RecipeLine"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeLine.id",
    )


class RecipeLine(TimestampMixin, Base):
    __tablename__ = "recipe_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(20), nullable=False)
    waste_factor: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False, default=0)

    recipe: Mapped["Recipe"] = relationship(back_populates="lines")
    ingredient_product: Mapped["Product"] = relationship()
