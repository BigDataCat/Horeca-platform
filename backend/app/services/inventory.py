from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inventory import ProductStock, StockMovement
from app.models.location import Location
from app.models.product import Product
from app.services.sales_ingestion import normalize_quantity


def own_location(db: Session, company_id: int, location_id: int) -> Location:
    location = db.get(Location, location_id)
    if location is None or location.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
    return location


def own_products(db: Session, company_id: int, product_ids: set[int]) -> dict[int, Product]:
    products = {
        p.id: p
        for p in db.scalars(select(Product).where(Product.company_id == company_id, Product.id.in_(product_ids))).all()
    }
    if len(products) != len(product_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more products were not found")
    return products


def to_base_uom(db: Session, company_id: int, product: Product, quantity: Decimal, uom: str) -> tuple[Decimal, Decimal]:
    """Convert to the product base UOM using explicit conversions. Returns (base_quantity, factor)."""
    base_quantity, resulting_uom = normalize_quantity(db, company_id, product, quantity, uom)
    if resulting_uom != product.base_uom.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No UOM conversion from {uom.upper()} to {product.base_uom.upper()} for product {product.id}",
        )
    return base_quantity, base_quantity / quantity


def get_stock(db: Session, company_id: int, location_id: int, product: Product, create: bool = True) -> ProductStock | None:
    stock = db.scalar(
        select(ProductStock).where(
            ProductStock.company_id == company_id,
            ProductStock.location_id == location_id,
            ProductStock.product_id == product.id,
        )
    )
    if stock is None and create:
        stock = ProductStock(
            company_id=company_id,
            location_id=location_id,
            product_id=product.id,
            quantity=Decimal("0"),
            uom=product.base_uom.upper(),
        )
        db.add(stock)
        db.flush()
    return stock


def move_stock(
    db: Session,
    company_id: int,
    location_id: int,
    product: Product,
    delta: Decimal,
    movement_type: str,
    reference_type: str,
    reference_id: str,
    occurred_at: datetime,
    note: str | None = None,
) -> None:
    stock = get_stock(db, company_id, location_id, product)
    stock.quantity += delta
    stock.uom = product.base_uom.upper()
    db.add(
        StockMovement(
            company_id=company_id,
            location_id=location_id,
            product_id=product.id,
            movement_type=movement_type,
            quantity=delta,
            uom=product.base_uom.upper(),
            reference_type=reference_type,
            reference_id=reference_id,
            occurred_at=occurred_at,
            note=note,
        )
    )
