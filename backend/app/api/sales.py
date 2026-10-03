from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.pos_integration import POSIntegration
from app.models.sale import Sale, SaleLine
from app.models.user import User
from app.schemas.sales import (
    SaleStatusChange,
    SaleRead,
    SalesImportRequest,
    SalesImportResult,
    UnmatchedProductRead,
)
from app.services.sales_ingestion import change_sale_status, import_sale

router = APIRouter(prefix="/sales", tags=["sales"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("", response_model=list[SaleRead])
def list_sales(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Sale]:
    return list(
        db.scalars(
            select(Sale)
            .options(selectinload(Sale.lines))
            .where(Sale.company_id == current_user.company_id)
            .order_by(Sale.occurred_at.desc())
        ).all()
    )


@router.post("/{sale_id}/status", response_model=SaleRead)
def change_status(
    sale_id: int,
    payload: SaleStatusChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Sale:
    """Cancel or refund a sale (full sale). Ingredient consumption is given back to stock."""
    require_manager(current_user)
    sale = db.get(Sale, sale_id)
    if sale is None or sale.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    if not change_sale_status(db, sale, payload.status, payload.reason):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Sale is already {sale.status}")
    db.commit()
    return db.scalar(select(Sale).options(selectinload(Sale.lines)).where(Sale.id == sale.id))


@router.get("/unmatched-products", response_model=list[UnmatchedProductRead])
def list_unmatched_products(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UnmatchedProductRead]:
    rows = db.execute(
        select(
            Sale.integration_id,
            SaleLine.external_product_id,
            SaleLine.product_name,
            SaleLine.uom,
            func.count(SaleLine.id).label("occurrences"),
            func.sum(SaleLine.quantity).label("total_quantity"),
        )
        .join(Sale, Sale.id == SaleLine.sale_id)
        .where(
            Sale.company_id == current_user.company_id,
            Sale.status == "completed",
            SaleLine.product_id.is_(None),
            Sale.integration_id.is_not(None),
            SaleLine.external_product_id.is_not(None),
        )
        .group_by(
            Sale.integration_id,
            SaleLine.external_product_id,
            SaleLine.product_name,
            SaleLine.uom,
        )
        .order_by(func.count(SaleLine.id).desc(), SaleLine.product_name)
    ).all()

    return [
        UnmatchedProductRead(
            integration_id=row.integration_id,
            external_product_id=row.external_product_id,
            product_name=row.product_name,
            uom=row.uom,
            occurrences=row.occurrences,
            total_quantity=row.total_quantity,
        )
        for row in rows
    ]


@router.post("/import", response_model=SalesImportResult)
def import_sales(
    payload: SalesImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalesImportResult:
    require_manager(current_user)

    integration = db.get(POSIntegration, payload.integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    if not integration.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POS integration is inactive")

    imported = 0
    skipped_duplicates = 0

    try:
        for canonical_sale in payload.sales:
            if import_sale(db, integration, canonical_sale):
                imported += 1
            else:
                skipped_duplicates += 1

        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return SalesImportResult(imported=imported, skipped_duplicates=skipped_duplicates)
