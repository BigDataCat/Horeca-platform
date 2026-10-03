from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.company import Company
from app.models.product_cost import ProductCost
from app.models.purchasing import GoodsReceipt, GoodsReceiptLine, Supplier
from app.models.user import User
from app.schemas.purchasing import (
    GoodsReceiptCreate,
    GoodsReceiptRead,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)
from app.services.inventory import move_stock, own_location, own_products, to_base_uom

router = APIRouter(tags=["purchasing"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


def own_supplier(db: Session, user: User, supplier_id: int) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


@router.get("/suppliers", response_model=list[SupplierRead])
def list_suppliers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Supplier]:
    return list(
        db.scalars(select(Supplier).where(Supplier.company_id == current_user.company_id).order_by(Supplier.name)).all()
    )


@router.post("/suppliers", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Supplier:
    require_manager(current_user)
    supplier = Supplier(company_id=current_user.company_id, **payload.model_dump())
    db.add(supplier)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A supplier with this name already exists")
    db.refresh(supplier)
    return supplier


@router.patch("/suppliers/{supplier_id}", response_model=SupplierRead)
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Supplier:
    require_manager(current_user)
    supplier = own_supplier(db, current_user, supplier_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A supplier with this name already exists")
    db.refresh(supplier)
    return supplier


@router.post("/inventory/receipts", response_model=GoodsReceiptRead, status_code=status.HTTP_201_CREATED)
def create_receipt(
    payload: GoodsReceiptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GoodsReceipt:
    """Post a goods receipt: stock goes up and the purchase price becomes the product's latest cost
    for the receiving location (last-purchase-price costing)."""
    require_manager(current_user)
    company_id = current_user.company_id
    own_location(db, company_id, payload.location_id)
    supplier = own_supplier(db, current_user, payload.supplier_id) if payload.supplier_id else None
    if supplier is not None and not supplier.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier is inactive")
    products = own_products(db, company_id, {line.product_id for line in payload.lines})

    company = db.get(Company, company_id)
    currency = (payload.currency or (company.currency if company else "RON")).upper()
    received_at = payload.received_at or datetime.now(timezone.utc)

    receipt = GoodsReceipt(
        company_id=company_id,
        location_id=payload.location_id,
        supplier_id=payload.supplier_id,
        document_number=payload.document_number,
        received_at=received_at,
        currency=currency,
        note=payload.note,
        created_by_id=current_user.id,
    )
    prepared = []
    for line in payload.lines:
        product = products[line.product_id]
        base_quantity, factor = to_base_uom(db, company_id, product, line.quantity, line.uom)
        base_cost = line.unit_cost / factor
        receipt.lines.append(
            GoodsReceiptLine(
                product_id=product.id,
                quantity=base_quantity,
                uom=product.base_uom.upper(),
                unit_cost=base_cost,
            )
        )
        prepared.append((product, base_quantity, base_cost))

    db.add(receipt)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A receipt with this document number already exists for the supplier",
        )

    for product, base_quantity, base_cost in prepared:
        move_stock(
            db, company_id, payload.location_id, product, base_quantity,
            "receipt", "receipt", str(receipt.id), received_at,
            note=f"Goods receipt {payload.document_number or receipt.id}",
        )
        db.add(
            ProductCost(
                company_id=company_id,
                product_id=product.id,
                location_id=payload.location_id,
                unit_cost=base_cost,
                currency=currency,
                effective_from=received_at,
            )
        )
    db.commit()
    return db.scalar(select(GoodsReceipt).options(selectinload(GoodsReceipt.lines)).where(GoodsReceipt.id == receipt.id))


@router.get("/inventory/receipts", response_model=list[GoodsReceiptRead])
def list_receipts(
    location_id: int | None = None,
    supplier_id: int | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GoodsReceipt]:
    query = (
        select(GoodsReceipt)
        .options(selectinload(GoodsReceipt.lines))
        .where(GoodsReceipt.company_id == current_user.company_id)
    )
    if location_id is not None:
        query = query.where(GoodsReceipt.location_id == location_id)
    if supplier_id is not None:
        query = query.where(GoodsReceipt.supplier_id == supplier_id)
    return list(db.scalars(query.order_by(GoodsReceipt.received_at.desc(), GoodsReceipt.id.desc()).limit(min(max(limit, 1), 500))).all())


@router.get("/inventory/receipts/{receipt_id}", response_model=GoodsReceiptRead)
def get_receipt(
    receipt_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> GoodsReceipt:
    receipt = db.scalar(
        select(GoodsReceipt).options(selectinload(GoodsReceipt.lines)).where(GoodsReceipt.id == receipt_id)
    )
    if receipt is None or receipt.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    return receipt
