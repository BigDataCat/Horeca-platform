from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.inventory import ProductStock, StockMovement
from app.models.location import Location
from app.models.product import Product
from app.models.user import User
from app.schemas.inventory import StockAdjustmentCreate, StockMovementRead, StockRead

router = APIRouter(prefix="/inventory", tags=["inventory"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("/stock", response_model=list[StockRead])
def list_stock(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ProductStock]:
    return list(
        db.scalars(
            select(ProductStock)
            .where(ProductStock.company_id == current_user.company_id)
            .order_by(ProductStock.location_id, ProductStock.product_id)
        ).all()
    )


@router.get("/movements", response_model=list[StockMovementRead])
def list_movements(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[StockMovement]:
    return list(
        db.scalars(
            select(StockMovement)
            .where(StockMovement.company_id == current_user.company_id)
            .order_by(StockMovement.occurred_at.desc())
            .limit(500)
        ).all()
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
            uom=payload.uom,
        )
        db.add(stock)

    stock.quantity += payload.quantity
    stock.uom = payload.uom

    movement = StockMovement(
        company_id=current_user.company_id,
        location_id=payload.location_id,
        product_id=payload.product_id,
        movement_type=payload.movement_type,
        quantity=payload.quantity,
        uom=payload.uom,
        reference_type="manual",
        occurred_at=datetime.now(timezone.utc),
        note=payload.note,
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement
