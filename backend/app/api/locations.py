from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.company import Company
from app.models.location import Location
from app.models.user import User
from app.services.plans import enforce_limit
from app.schemas.location import LocationCreate, LocationRead, LocationUpdate

router = APIRouter(prefix="/locations", tags=["locations"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("", response_model=list[LocationRead])
def list_locations(
    company_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Location]:
    requested_company_id = company_id or current_user.company_id

    if requested_company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company access denied")

    return list(
        db.scalars(
            select(Location)
            .where(Location.company_id == current_user.company_id)
            .order_by(Location.id)
        ).all()
    )


@router.get("/{location_id}", response_model=LocationRead)
def get_location(
    location_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Location:
    location = db.get(Location, location_id)

    if location is None or location.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    return location


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(
    payload: LocationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Location:
    require_manager(current_user)

    if payload.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company access denied")

    enforce_limit(db, current_user.company_id, "locations")
    location = Location(**payload.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


@router.patch("/{location_id}", response_model=LocationRead)
def update_location(
    location_id: int,
    payload: LocationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Location:
    require_manager(current_user)
    location = db.get(Location, location_id)

    if location is None or location.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    if payload.active is True and not location.active:
        enforce_limit(db, current_user.company_id, "locations")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, field, value)

    db.commit()
    db.refresh(location)
    return location


@router.delete("/{location_id}", response_model=LocationRead)
def deactivate_location(
    location_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Location:
    require_manager(current_user)
    location = db.get(Location, location_id)

    if location is None or location.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    location.active = False
    db.commit()
    db.refresh(location)
    return location
