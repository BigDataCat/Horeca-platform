import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import clamp_page, set_total
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.company import Company
from app.models.user import User
from app.services.plans import PLANS, get_plan, usage

router = APIRouter(tags=["saas"])


class SubscriptionRead(BaseModel):
    plan: str
    limits: dict[str, int | None]
    usage: dict[str, int]


def _subscription(db: Session, company: Company) -> SubscriptionRead:
    plan = get_plan(company.plan)
    return SubscriptionRead(
        plan=plan.name,
        limits={"locations": plan.max_locations, "users": plan.max_users, "integrations": plan.max_integrations},
        usage=usage(db, company.id),
    )


@router.get("/subscription", response_model=SubscriptionRead)
def get_subscription(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SubscriptionRead:
    return _subscription(db, db.get(Company, current_user.company_id))


# ---- platform administration (support tooling), protected by ADMIN_API_KEY ----
def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not x_admin_key or not hmac.compare_digest(settings.admin_api_key, x_admin_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


class AdminCompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tax_identifier: str | None
    plan: str
    active: bool
    created_at: datetime
    usage: dict[str, int] = {}


class AdminCompanyUpdate(BaseModel):
    plan: str | None = None
    active: bool | None = None


def _admin_view(db: Session, company: Company) -> AdminCompanyRead:
    view = AdminCompanyRead.model_validate(company)
    view.usage = usage(db, company.id)
    return view


@router.get("/admin/companies", response_model=list[AdminCompanyRead], dependencies=[Depends(require_admin)])
def admin_list_companies(
    response: Response,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[AdminCompanyRead]:
    query = select(Company)
    if q:
        query = query.where(func.lower(Company.name).contains(q.lower(), autoescape=True))
    set_total(response, db, query)
    limit, offset = clamp_page(limit, offset)
    return [_admin_view(db, c) for c in db.scalars(query.order_by(Company.id).limit(limit).offset(offset)).all()]


@router.patch("/admin/companies/{company_id}", response_model=AdminCompanyRead, dependencies=[Depends(require_admin)])
def admin_update_company(company_id: int, payload: AdminCompanyUpdate, db: Session = Depends(get_db)) -> AdminCompanyRead:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    if payload.plan is not None:
        if payload.plan not in PLANS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown plan. Choose one of: {', '.join(PLANS)}")
        company.plan = payload.plan
    if payload.active is not None:
        company.active = payload.active
    db.commit()
    db.refresh(company)
    return _admin_view(db, company)
