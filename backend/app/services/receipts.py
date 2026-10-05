from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.company import Company
from app.models.product_cost import ProductCost
from app.models.purchasing import GoodsReceipt, GoodsReceiptLine, Supplier
from app.schemas.purchasing import GoodsReceiptCreate
from app.services.inventory import move_stock, own_location, own_products, to_base_uom


def post_goods_receipt(db: Session, company_id: int, user_id: int | None, payload: GoodsReceiptCreate) -> GoodsReceipt:
    """Post a goods receipt: stock goes up and the purchase price becomes the product's latest cost
    for the receiving location (last-purchase-price costing). Used by the API and by invoice import."""
    own_location(db, company_id, payload.location_id)
    supplier = None
    if payload.supplier_id:
        supplier = db.get(Supplier, payload.supplier_id)
        if supplier is None or supplier.company_id != company_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
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
        created_by_id=user_id,
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
