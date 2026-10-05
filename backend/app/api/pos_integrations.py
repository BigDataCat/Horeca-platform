import hashlib
import secrets
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
    WebhookTokenResponse,
    POSSyncResult,
)
from app.schemas.sync_runs import SyncRunRead
from app.services.pos_connectors import get_connector
from app.services.plans import enforce_limit
from app.services.sync import run_sync

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


def reject_secrets_in_config(config: dict | None) -> None:
    if config and "webhook_token" in config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Do not store webhook tokens in config; generate one with POST /{id}/webhook-token",
        )


@router.post("", response_model=POSIntegrationRead, status_code=status.HTTP_201_CREATED)
def create_integration(
    payload: POSIntegrationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> POSIntegration:
    require_manager(current_user)
    reject_secrets_in_config(payload.config)

    location = db.get(Location, payload.location_id)

    if location is None or location.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    enforce_limit(db, current_user.company_id, "integrations")

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
        sync_interval_minutes=payload.sync_interval_minutes,
        next_sync_at=datetime.now(timezone.utc) if payload.sync_interval_minutes else None,
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
    reject_secrets_in_config(payload.config)

    integration = db.get(POSIntegration, integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    values = payload.model_dump(exclude_unset=True)
    if values.get("active") is True and not integration.active:
        enforce_limit(db, current_user.company_id, "integrations")
    for field, value in values.items():
        setattr(integration, field, value)

    if "sync_interval_minutes" in values:
        # (Re)configuring the schedule resumes a paused integration.
        integration.consecutive_failures = 0
        integration.sync_paused_reason = None
        integration.next_sync_at = datetime.now(timezone.utc) if values["sync_interval_minutes"] else None

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

    outcome = run_sync(db, integration, trigger="manual")

    if outcome.error is not None:
        if isinstance(outcome.error, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(outcome.error))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"POS sync failed: {outcome.error}")

    sync_run = outcome.sync_run
    return POSSyncResult(
        integration_id=integration.id,
        provider=integration.provider,
        fetched=sync_run.fetched,
        imported=sync_run.imported,
        skipped_duplicates=sync_run.skipped_duplicates,
    )


@router.post("/{integration_id}/webhook-token", response_model=WebhookTokenResponse)
def rotate_webhook_token(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WebhookTokenResponse:
    """Generate (or rotate) the webhook token. Only its SHA-256 hash is stored."""
    require_manager(current_user)

    integration = db.get(POSIntegration, integration_id)

    if integration is None or integration.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS integration not found")

    token = secrets.token_urlsafe(32)
    integration.webhook_token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.commit()
    return WebhookTokenResponse(integration_id=integration.id, webhook_token=token)


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
    except Exception as exc:  # network/vendor outage while testing
        integration.status = "error"
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Connection test failed: {exc}")

    integration.status = "connected" if result.success else "error"
    db.commit()

    return ConnectionTestResult(
        integration_id=integration.id,
        provider=integration.provider,
        success=result.success,
        message=result.message,
    )
