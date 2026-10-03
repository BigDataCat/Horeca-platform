from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.location import Location
from app.models.pos_integration import POSIntegration
from app.models.sync_run import SyncRun
from app.models.user import User
from app.schemas.pos_integration import (
    ConnectionTestResult,
    POSIntegrationCreate,
    POSIntegrationRead,
    POSIntegrationUpdate,
    POSSyncResult,
)
from app.schemas.sync_runs import SyncRunRead
from app.services.pos_connectors import get_connector
from app.services.sales_ingestion import import_sale

router = APIRouter(prefix="/integrations/pos", tags=["pos-integrations"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or manager role required",
        )


@router.get("", response_model=list[POSIntegrationRead])
def list_integrations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[POSIntegration]:
    return list(
        db.scalars(
            select(POSIntegration)
            .where(POSIntegration.company_id == current_user.company_id)
            .order_by(POSIntegration.id)
        ).all()
    )


@router.get("/{integration_id}/sync-runs", response_model=list[SyncRunRead])
def list_sync_runs(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SyncRun]:
    integration = db.get(POSIntegration, integration_id)
    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    return list(
        db.scalars(
            select(SyncRun)
            .where(
                SyncRun.company_id == current_user.company_id,
                SyncRun.integration_id == integration_id,
            )
            .order_by(SyncRun.started_at.desc())
            .limit(50)
        ).all()
    )


@router.post("", response_model=POSIntegrationRead, status_code=status.HTTP_201_CREATED)
def create_integration(
    payload: POSIntegrationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> POSIntegration:
    require_manager(current_user)

    location = db.get(Location, payload.location_id)

    if location is None or location.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    integration = POSIntegration(
        company_id=current_user.company_id,
        location_id=payload.location_id,
        provider=payload.provider.lower(),
        name=payload.name,
        connection_type=payload.connection_type,
        status="inactive",
        base_url=payload.base_url,
        external_account_id=payload.external_account_id,
        credentials_ref=payload.credentials_ref,
        config=payload.config,
    )

    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration


@router.patch("/{integration_id}", response_model=POSIntegrationRead)
def update_integration(
    integration_id: int,
    payload: POSIntegrationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> POSIntegration:
    require_manager(current_user)

    integration = db.get(POSIntegration, integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(integration, field, value)

    db.commit()
    db.refresh(integration)
    return integration


@router.delete("/{integration_id}", response_model=POSIntegrationRead)
def deactivate_integration(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> POSIntegration:
    require_manager(current_user)

    integration = db.get(POSIntegration, integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    integration.active = False
    integration.status = "inactive"
    db.commit()
    db.refresh(integration)
    return integration


@router.post("/{integration_id}/sync", response_model=POSSyncResult)
def sync_integration(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> POSSyncResult:
    require_manager(current_user)

    integration = db.get(POSIntegration, integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    if not integration.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="POS integration is inactive")

    sync_run = SyncRun(
        company_id=integration.company_id,
        integration_id=integration.id,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.add(sync_run)
    db.commit()
    db.refresh(sync_run)

    try:
        connector = get_connector(integration.provider)
        sales = connector.pull_sales(integration)
        sync_run.fetched = len(sales)

        for sale in sales:
            if import_sale(db, integration, sale):
                sync_run.imported += 1
            else:
                sync_run.skipped_duplicates += 1

        integration.status = "connected"
        sync_run.status = "success"
        sync_run.finished_at = datetime.now(timezone.utc)
        db.commit()

    except ValueError as exc:
        db.rollback()
        sync_run = db.get(SyncRun, sync_run.id)
        if sync_run is not None:
            sync_run.status = "error"
            sync_run.finished_at = datetime.now(timezone.utc)
            sync_run.error_message = str(exc)
            db.commit()
        integration.status = "error"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    except Exception as exc:
        db.rollback()
        sync_run = db.get(SyncRun, sync_run.id)
        if sync_run is not None:
            sync_run.status = "error"
            sync_run.finished_at = datetime.now(timezone.utc)
            sync_run.error_message = str(exc)
            db.commit()
        integration.status = "error"
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"POS sync failed: {exc}")

    return POSSyncResult(
        integration_id=integration.id,
        provider=integration.provider,
        fetched=sync_run.fetched,
        imported=sync_run.imported,
        skipped_duplicates=sync_run.skipped_duplicates,
    )


@router.post("/{integration_id}/test", response_model=ConnectionTestResult)
def test_integration(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectionTestResult:
    require_manager(current_user)

    integration = db.get(POSIntegration, integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    try:
        connector = get_connector(integration.provider)
        result = connector.test_connection(integration)
    except ValueError as exc:
        integration.status = "error"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    integration.status = "connected" if result.success else "error"
    db.commit()

    return ConnectionTestResult(
        integration_id=integration.id,
        provider=integration.provider,
        success=result.success,
        message=result.message,
    )
