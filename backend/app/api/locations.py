from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.company import Company
from app.models.location import Location
from app.schemas.location import LocationCreate, LocationRead, LocationUpdate

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=list[LocationRead])
def list_locations(
    company_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[Location]:
    query = select(Location).order_by(Location.id)

    if company_id is not None:
        query = query.where(Location.company_id == company_id)

    return list(db.scalars(query).all())


@router.get("/{location_id}", response_model=LocationRead)
def get_location(location_id: int, db: Session = Depends(get_db)) -> Location:
    location = db.get(Location, location_id)

    if location is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    return location


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(
    payload: LocationCreate,
    db: Session = Depends(get_db),
) -> Location:
    company = db.get(Company, payload.company_id)

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )

    location = Location(**payload.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)

    return location


@router.patch("/{location_id}", response_model=LocationRead)
def update_location(
    location_id: int,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
) -> Location:
    location = db.get(Location, location_id)

    if location is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, field, value)

    db.commit()
    db.refresh(location)

    return location


@router.delete("/{location_id}", response_model=LocationRead)
def deactivate_location(
    location_id: int,
    db: Session = Depends(get_db),
) -> Location:
    location = db.get(Location, location_id)

    if location is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    location.active = False
    db.commit()
    db.refresh(location)

    return location
