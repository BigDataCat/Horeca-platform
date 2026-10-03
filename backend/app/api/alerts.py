from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.alerts import compute_alerts

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertRead(BaseModel):
    type: str
    severity: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None


@router.get("", response_model=list[AlertRead])
def list_alerts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Operational alerts computed from current data (stock, sync health, mapping and cost gaps)."""
    return compute_alerts(db, current_user.company_id)
