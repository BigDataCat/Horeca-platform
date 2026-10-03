import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, hash_password
from app.models.user import User
from app.services.plans import enforce_limit
from app.schemas.user import PasswordReset, UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def require_manager(user: User) -> None:
    if user.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner or manager role required")


@router.get("", response_model=list[UserRead])
def list_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.company_id == current_user.company_id)
            .order_by(User.id)
        ).all()
    )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    require_manager(current_user)

    if payload.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company access denied")

    if current_user.role == "manager" and payload.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers cannot create owners")

    enforce_limit(db, current_user.company_id, "users")

    user = User(
        company_id=current_user.company_id,
        email=str(payload.email).lower(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    require_manager(current_user)

    user = db.get(User, user_id)

    if user is None or user.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id and payload.active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")

    if current_user.role == "manager" and payload.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers cannot promote users to owner")

    values = payload.model_dump(exclude_unset=True)
    if values.get("active") is True and not user.active:
        enforce_limit(db, current_user.company_id, "users")
    if ("role" in values and values["role"] != user.role) or values.get("active") is False:
        # Role changes and deactivation take effect immediately, not when the token expires.
        user.token_version += 1

    for field, value in values.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=UserRead)
def deactivate_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    require_manager(current_user)

    user = db.get(User, user_id)

    if user is None or user.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")

    if current_user.role == "manager" and user.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers cannot deactivate owners")

    user.active = False
    user.token_version += 1
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=UserRead)
def reset_user_password(
    user_id: int,
    payload: PasswordReset,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Administrative reset: sets a new password and signs the user out everywhere."""
    require_manager(current_user)

    user = db.get(User, user_id)

    if user is None or user.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use change-password for your own account")

    if current_user.role == "manager" and user.role == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers cannot reset owner passwords")

    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/anonymize", response_model=UserRead)
def anonymize_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """GDPR erasure: removes the person's identifying data and locks the account.

    Business records they created (audit log entries, receipts, counts) are kept and keep
    pointing to the now-anonymous user, so history stays consistent without personal data."""
    if current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")

    user = db.get(User, user_id)

    if user is None or user.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Owners cannot anonymize their own account")

    user.email = f"anonymized-{user.id}@example.com"
    user.first_name = "Deleted"
    user.last_name = "User"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.active = False
    user.token_version += 1
    db.commit()
    db.refresh(user)
    return user
