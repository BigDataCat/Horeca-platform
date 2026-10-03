from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.product import Product
from app.models.user import User
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("", response_model=list[ProductRead])
def list_products(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Product]:
    return list(
        db.scalars(
            select(Product)
            .where(Product.company_id == current_user.company_id)
            .order_by(Product.name)
        ).all()
    )


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Product:
    require_manager(current_user)

    product = Product(
        company_id=current_user.company_id,
        sku=payload.sku,
        name=payload.name,
        category=payload.category,
        base_uom=payload.base_uom.upper(),
    )
    db.add(product)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not create product")

    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Product:
    require_manager(current_user)

    product = db.get(Product, product_id)

    if product is None or product.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    values = payload.model_dump(exclude_unset=True)
    if "base_uom" in values and values["base_uom"] is not None:
        values["base_uom"] = values["base_uom"].upper()

    for field, value in values.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product
