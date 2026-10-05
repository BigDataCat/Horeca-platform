from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.common import clamp_page, csv_response, set_total
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.pos_integration import POSIntegration
from app.models.sale import Sale, SaleLine
from app.models.company import Company
from app.models.user import User
from app.schemas.sales import (
    SaleRefundRequest,
    SaleStatusChange,
    SaleRead,
    SalesImportRequest,
    SalesImportResult,
    UnmatchedProductRead,
)
from app.services.csv_sales import CSVImportError, parse_csv_sales
from app.services.sales_ingestion import ACTIVE_STATUSES, RefundError, change_sale_status, import_sale, refund_sale_lines

router = APIRouter(prefix="/sales", tags=["sales"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


def sale_query(
    company_id: int,
    location_id: int | None,
    integration_id: int | None,
    sale_status: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    query = select(Sale).where(Sale.company_id == company_id)
    if location_id is not None:
        query = query.where(Sale.location_id == location_id)
    if integration_id is not None:
        query = query.where(Sale.integration_id == integration_id)
    if sale_status:
        query = query.where(Sale.status == sale_status)
    if date_from:
        query = query.where(Sale.occurred_at >= date_from)
    if date_to:
        query = query.where(Sale.occurred_at < date_to)
    return query


@router.get("", response_model=list[SaleRead])
def list_sales(
    response: Response,
    location_id: int | None = None,
    integration_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Sale]:
    query = sale_query(current_user.company_id, location_id, integration_id, status_filter, date_from, date_to)
    set_total(response, db, query)
    limit, offset = clamp_page(limit, offset)
    return list(
        db.scalars(
            query.options(selectinload(Sale.lines))
            .order_by(Sale.occurred_at.desc(), Sale.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )


@router.get("/export.csv")
def export_sales(
    location_id: int | None = None,
    integration_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """One row per sale line (max 50,000 rows)."""
    query = sale_query(current_user.company_id, location_id, integration_id, status_filter, date_from, date_to)
    sales = db.scalars(
        query.options(selectinload(Sale.lines)).order_by(Sale.occurred_at, Sale.id).limit(10000)
    ).all()
    rows = []
    for sale in sales:
        for sale_line in sale.lines:
            rows.append(
                [
                    sale.external_id, sale.occurred_at.isoformat(), sale.location_id, sale.integration_id, sale.status,
                    sale.currency, sale_line.product_id, sale_line.external_product_id, sale_line.product_name,
                    sale_line.quantity, sale_line.uom, sale_line.unit_price, sale_line.net_value, sale_line.tax_value,
                ]
            )
    return csv_response(
        "sales.csv",
        ["sale_id", "occurred_at", "location_id", "integration_id", "status", "currency", "product_id",
         "external_product_id", "product_name", "quantity", "uom", "unit_price", "net_value", "tax_value"],
        rows[:50000],
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


@router.post("/{sale_id}/refund-lines", response_model=SaleRead)
def refund_lines(
    sale_id: int,
    payload: SaleRefundRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Sale:
    """Refund part of a sale (per line and quantity). Revenue and ingredient stock are reversed proportionally."""
    require_manager(current_user)
    sale = db.scalar(select(Sale).options(selectinload(Sale.lines)).where(Sale.id == sale_id))
    if sale is None or sale.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    try:
        refund_sale_lines(db, sale, [(l.line_id, l.quantity) for l in payload.lines], payload.reason)
    except RefundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT if "already" in str(exc) else status.HTTP_400_BAD_REQUEST, detail=str(exc))
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
            Sale.status.in_(ACTIVE_STATUSES),
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


MAX_CSV_BYTES = 5 * 1024 * 1024


@router.post("/import-csv", response_model=SalesImportResult)
async def import_sales_csv(
    request: Request,
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalesImportResult:
    """Import sales from a CSV export (raw ``text/csv`` request body). All-or-nothing."""
    require_manager(current_user)

    integration = db.get(POSIntegration, integration_id)
    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")
    if not integration.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POS integration is inactive")

    body = await request.body()
    if len(body) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV file is too large (5 MB maximum)")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV must be UTF-8 encoded")

    company = db.get(Company, current_user.company_id)
    try:
        sales = parse_csv_sales(text, company.currency if company else "RON")
    except CSVImportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors)

    imported = 0
    skipped_duplicates = 0
    try:
        for canonical_sale in sales:
            if import_sale(db, integration, canonical_sale):
                imported += 1
            else:
                skipped_duplicates += 1
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return SalesImportResult(imported=imported, skipped_duplicates=skipped_duplicates)
