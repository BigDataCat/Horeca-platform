from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.pos_integration import POSIntegration
from app.models.user import User
from app.schemas.sales import SalesImportRequest, SalesImportResult
from app.services.sales_ingestion import import_sale

router = APIRouter(prefix="/sales", tags=["sales"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or manager role required",
        )


@router.post("/import", response_model=SalesImportResult)
def import_sales(
    payload: SalesImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalesImportResult:
    require_manager(current_user)

    integration = db.get(POSIntegration, payload.integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POS integration not found",
        )

    if not integration.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="POS integration is inactive",
        )

    imported = 0
    skipped_duplicates = 0

    for canonical_sale in payload.sales:
        if import_sale(db, integration, canonical_sale):
            imported += 1
        else:
            skipped_duplicates += 1

    db.commit()

    return SalesImportResult(
        imported=imported,
        skipped_duplicates=skipped_duplicates,
    )
