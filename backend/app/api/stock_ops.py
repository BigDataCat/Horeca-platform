from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.stock_ops import StockCount, StockCountLine, StockTransfer, StockTransferLine
from app.models.user import User
from app.schemas.stock_ops import StockCountCreate, StockCountRead, StockTransferCreate, StockTransferRead
from app.services.inventory import get_stock, move_stock, own_location, own_products, to_base_uom

router = APIRouter(prefix="/inventory", tags=["stock-operations"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


def reject_duplicate_products(product_ids: list[int]) -> None:
    if len(product_ids) != len(set(product_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A product can appear only once per document")


@router.post("/counts", response_model=StockCountRead, status_code=status.HTTP_201_CREATED)
def create_count(
    payload: StockCountCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> StockCount:
    """Physical stock count: the counted quantity replaces the book quantity; differences are recorded."""
    require_manager(current_user)
    company_id = current_user.company_id
    own_location(db, company_id, payload.location_id)
    reject_duplicate_products([l.product_id for l in payload.lines])
    products = own_products(db, company_id, {l.product_id for l in payload.lines})
    counted_at = payload.counted_at or datetime.now(timezone.utc)

    count = StockCount(
        company_id=company_id,
        location_id=payload.location_id,
        counted_at=counted_at,
        note=payload.note,
        created_by_id=current_user.id,
    )
    db.add(count)
    db.flush()

    for line in payload.lines:
        product = products[line.product_id]
        counted, _ = to_base_uom(db, company_id, product, line.counted_quantity, line.uom) if line.counted_quantity else (Decimal("0"), Decimal("1"))
        stock = get_stock(db, company_id, payload.location_id, product, create=False)
        expected = stock.quantity if stock is not None else Decimal("0")
        difference = counted - expected
        count.lines.append(
            StockCountLine(
                product_id=product.id,
                expected_quantity=expected,
                counted_quantity=counted,
                difference=difference,
                uom=product.base_uom.upper(),
            )
        )
        if difference != 0:
            move_stock(
                db, company_id, payload.location_id, product, difference,
                "count_adjustment", "stock_count", str(count.id), counted_at,
                note=f"Stock count {count.id}",
            )
    db.commit()
    return db.scalar(select(StockCount).options(selectinload(StockCount.lines)).where(StockCount.id == count.id))


@router.get("/counts", response_model=list[StockCountRead])
def list_counts(
    location_id: int | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StockCount]:
    query = select(StockCount).options(selectinload(StockCount.lines)).where(StockCount.company_id == current_user.company_id)
    if location_id is not None:
        query = query.where(StockCount.location_id == location_id)
    return list(db.scalars(query.order_by(StockCount.counted_at.desc(), StockCount.id.desc()).limit(min(max(limit, 1), 500))).all())


@router.post("/transfers", response_model=StockTransferRead, status_code=status.HTTP_201_CREATED)
def create_transfer(
    payload: StockTransferCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> StockTransfer:
    """Move stock between two locations of the same company. The source must hold enough stock."""
    require_manager(current_user)
    company_id = current_user.company_id
    if payload.from_location_id == payload.to_location_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source and destination must differ")
    own_location(db, company_id, payload.from_location_id)
    own_location(db, company_id, payload.to_location_id)
    reject_duplicate_products([l.product_id for l in payload.lines])
    products = own_products(db, company_id, {l.product_id for l in payload.lines})
    transferred_at = payload.transferred_at or datetime.now(timezone.utc)

    prepared = []
    for line in payload.lines:
        product = products[line.product_id]
        quantity, _ = to_base_uom(db, company_id, product, line.quantity, line.uom)
        stock = get_stock(db, company_id, payload.from_location_id, product, create=False)
        available = stock.quantity if stock is not None else Decimal("0")
        if available < quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for product {product.id}: {available} available, {quantity} requested",
            )
        prepared.append((product, quantity))

    transfer = StockTransfer(
        company_id=company_id,
        from_location_id=payload.from_location_id,
        to_location_id=payload.to_location_id,
        transferred_at=transferred_at,
        note=payload.note,
        created_by_id=current_user.id,
    )
    db.add(transfer)
    db.flush()

    for product, quantity in prepared:
        transfer.lines.append(StockTransferLine(product_id=product.id, quantity=quantity, uom=product.base_uom.upper()))
        reference = str(transfer.id)
        move_stock(db, company_id, payload.from_location_id, product, -quantity, "transfer_out", "transfer", reference, transferred_at, note=f"Transfer {transfer.id} out")
        move_stock(db, company_id, payload.to_location_id, product, quantity, "transfer_in", "transfer", reference, transferred_at, note=f"Transfer {transfer.id} in")
    db.commit()
    return db.scalar(select(StockTransfer).options(selectinload(StockTransfer.lines)).where(StockTransfer.id == transfer.id))


@router.get("/transfers", response_model=list[StockTransferRead])
def list_transfers(
    limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[StockTransfer]:
    return list(
        db.scalars(
            select(StockTransfer)
            .options(selectinload(StockTransfer.lines))
            .where(StockTransfer.company_id == current_user.company_id)
            .order_by(StockTransfer.transferred_at.desc(), StockTransfer.id.desc())
            .limit(min(max(limit, 1), 500))
        ).all()
    )
