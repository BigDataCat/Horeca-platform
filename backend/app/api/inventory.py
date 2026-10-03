from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import clamp_page, csv_response, set_total
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.inventory import ProductStock, StockMovement
from app.models.location import Location
from app.models.product import Product
from app.models.user import User
from app.schemas.inventory import StockAdjustmentCreate, StockMovementRead, StockRead
from app.services.sales_ingestion import normalize_quantity

router = APIRouter(prefix="/inventory", tags=["inventory"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("/stock", response_model=list[StockRead])
def list_stock(
    response: Response,
    location_id: int | None = None,
    product_id: int | None = None,
    limit: int = 1000,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProductStock]:
    query = select(ProductStock).where(ProductStock.company_id == current_user.company_id)
    if location_id is not None:
        query = query.where(ProductStock.location_id == location_id)
    if product_id is not None:
        query = query.where(ProductStock.product_id == product_id)
    set_total(response, db, query)
    limit, offset = clamp_page(limit, offset)
    return list(
        db.scalars(query.order_by(ProductStock.location_id, ProductStock.product_id).limit(limit).offset(offset)).all()
    )


def movement_query(
    company_id: int,
    location_id: int | None,
    product_id: int | None,
    movement_type: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    query = select(StockMovement).where(StockMovement.company_id == company_id)
    if location_id is not None:
        query = query.where(StockMovement.location_id == location_id)
    if product_id is not None:
        query = query.where(StockMovement.product_id == product_id)
    if movement_type:
        query = query.where(StockMovement.movement_type == movement_type)
    if date_from:
        query = query.where(StockMovement.occurred_at >= date_from)
    if date_to:
        query = query.where(StockMovement.occurred_at < date_to)
    return query


@router.get("/movements", response_model=list[StockMovementRead])
def list_movements(
    response: Response,
    location_id: int | None = None,
    product_id: int | None = None,
    movement_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StockMovement]:
    query = movement_query(current_user.company_id, location_id, product_id, movement_type, date_from, date_to)
    set_total(response, db, query)
    limit, offset = clamp_page(limit, offset)
    return list(
        db.scalars(query.order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc()).limit(limit).offset(offset)).all()
    )


@router.get("/movements/export.csv")
def export_movements(
    location_id: int | None = None,
    product_id: int | None = None,
    movement_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    query = movement_query(current_user.company_id, location_id, product_id, movement_type, date_from, date_to)
    rows = db.scalars(query.order_by(StockMovement.occurred_at, StockMovement.id).limit(50000)).all()
    return csv_response(
        "stock-movements.csv",
        ["id", "occurred_at", "location_id", "product_id", "movement_type", "quantity", "uom", "reference_type", "reference_id", "note"],
        [
            [m.id, m.occurred_at.isoformat(), m.location_id, m.product_id, m.movement_type, m.quantity, m.uom, m.reference_type, m.reference_id, m.note]
            for m in rows
        ],
    )


@router.post("/adjustments", response_model=StockMovementRead, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    payload: StockAdjustmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockMovement:
    require_manager(current_user)

    location = db.get(Location, payload.location_id)
    product = db.get(Product, payload.product_id)
    if location is None or location.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Location not found")
    if product is None or product.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Product not found")
    if payload.quantity == 0:
        raise HTTPException(status_code=400, detail="Adjustment quantity cannot be zero")

    # Stock is always held in the product base UOM; convert explicitly or refuse.
    quantity, uom = normalize_quantity(db, current_user.company_id, product, payload.quantity, payload.uom)
    if uom != product.base_uom.upper():
        raise HTTPException(
            status_code=400,
            detail=f"No UOM conversion from {payload.uom.upper()} to {product.base_uom.upper()} for this product",
        )

    stock = db.scalar(
        select(ProductStock).where(
            ProductStock.company_id == current_user.company_id,
            ProductStock.location_id == payload.location_id,
            ProductStock.product_id == payload.product_id,
        )
    )
    if stock is None:
        stock = ProductStock(
            company_id=current_user.company_id,
            location_id=payload.location_id,
            product_id=payload.product_id,
            quantity=Decimal("0"),
            uom=uom,
        )
        db.add(stock)

    stock.quantity += quantity
    stock.uom = uom

    movement = StockMovement(
        company_id=current_user.company_id,
        location_id=payload.location_id,
        product_id=payload.product_id,
        movement_type=payload.movement_type,
        quantity=quantity,
        uom=uom,
        reference_type="manual",
        occurred_at=datetime.now(timezone.utc),
        note=payload.note,
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement
