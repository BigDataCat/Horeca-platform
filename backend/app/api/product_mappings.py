from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.pos_integration import POSIntegration
from app.models.product import Product
from app.models.product_mapping import ProductMapping
from app.models.product_uom_conversion import ProductUOMConversion
from app.models.user import User
from app.schemas.product_mapping import (
    ProductMappingCreate,
    ProductMappingRead,
    ProductUOMConversionCreate,
    ProductUOMConversionRead,
)

router = APIRouter(prefix="/product-mappings", tags=["product-mappings"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or manager role required",
        )


@router.get("", response_model=list[ProductMappingRead])
def list_mappings(
    integration_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProductMapping]:
    query = select(ProductMapping).where(
        ProductMapping.company_id == current_user.company_id
    )
    if integration_id is not None:
        query = query.where(ProductMapping.integration_id == integration_id)
    return list(db.scalars(query.order_by(ProductMapping.external_product_name)).all())


@router.post("", response_model=ProductMappingRead, status_code=status.HTTP_201_CREATED)
def create_mapping(
    payload: ProductMappingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProductMapping:
    require_manager(current_user)

    integration = db.get(POSIntegration, payload.integration_id)
    product = db.get(Product, payload.product_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="POS integration not found")
    if product is None or product.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Product not found")

    mapping = ProductMapping(
        company_id=current_user.company_id,
        integration_id=payload.integration_id,
        external_product_id=payload.external_product_id,
        external_product_name=payload.external_product_name,
        product_id=payload.product_id,
        match_method=payload.match_method,
        confidence=1,
    )
    db.add(mapping)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A mapping already exists for this POS product and integration",
        )

    db.refresh(mapping)
    return mapping


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(
    mapping_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_manager(current_user)

    mapping = db.get(ProductMapping, mapping_id)
    if mapping is None or mapping.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Product mapping not found")

    db.delete(mapping)
    db.commit()


@router.get("/uom-conversions", response_model=list[ProductUOMConversionRead])
def list_uom_conversions(
    product_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProductUOMConversion]:
    query = select(ProductUOMConversion).where(
        ProductUOMConversion.company_id == current_user.company_id
    )
    if product_id is not None:
        query = query.where(ProductUOMConversion.product_id == product_id)
    return list(db.scalars(query.order_by(ProductUOMConversion.product_id)).all())


@router.post(
    "/uom-conversions",
    response_model=ProductUOMConversionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_uom_conversion(
    payload: ProductUOMConversionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProductUOMConversion:
    require_manager(current_user)

    product = db.get(Product, payload.product_id)
    if product is None or product.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Product not found")

    from_uom = payload.from_uom.upper()
    to_uom = payload.to_uom.upper()

    conversion = ProductUOMConversion(
        company_id=current_user.company_id,
        product_id=payload.product_id,
        from_uom=from_uom,
        to_uom=to_uom,
        factor=payload.factor,
    )
    db.add(conversion)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This UOM conversion already exists for the product",
        )

    db.refresh(conversion)
    return conversion


@router.delete("/uom-conversions/{conversion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_uom_conversion(
    conversion_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    require_manager(current_user)

    conversion = db.get(ProductUOMConversion, conversion_id)
    if conversion is None or conversion.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="UOM conversion not found")

    db.delete(conversion)
    db.commit()
