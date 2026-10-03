from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.models.company import Company
from app.models.user import User
from app.schemas.user import BootstrapRequest, TokenResponse, UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])

login_limiter = SlidingWindowLimiter(settings.login_max_attempts, settings.login_window_seconds)


@router.post("/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def bootstrap_company(payload: BootstrapRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing_user = db.scalar(
        select(User).where(func.lower(User.email) == str(payload.email).lower())
    )

    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    company = Company(
        name=payload.company_name,
        tax_identifier=payload.tax_identifier,
        currency=payload.currency.upper(),
    )
    db.add(company)
    db.flush()

    user = User(
        company_id=company.id,
        email=str(payload.email).lower(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        password_hash=hash_password(payload.password),
        role="owner",
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not create the company and owner account")

    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user), user=user)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    company = db.get(Company, payload.company_id)

    if company is None or not company.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    existing_count = db.scalar(
        select(func.count()).select_from(User).where(User.company_id == payload.company_id)
    )

    if existing_count and existing_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The company already has users. Use an authenticated company user to create additional users.",
        )

    user = User(
        company_id=payload.company_id,
        email=str(payload.email).lower(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        password_hash=hash_password(payload.password),
        role="owner",
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(payload.email).lower()
    client_host = request.client.host if request.client else "unknown"
    limiter_keys = (f"email:{email}", f"ip:{client_host}")

    if any(login_limiter.is_blocked(key) for key in limiter_keys):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(settings.login_window_seconds)},
        )

    user = db.scalar(select(User).where(func.lower(User.email) == email))

    if user is None or not verify_password(payload.password, user.password_hash):
        for key in limiter_keys:
            login_limiter.record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    login_limiter.reset(limiter_keys[0])
    return TokenResponse(access_token=create_access_token(user), user=user)


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
