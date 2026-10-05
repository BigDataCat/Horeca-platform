from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )

    payload = {
        "sub": str(user.id),
        "company_id": user.company_id,
        "role": user.role,
        "tv": user.token_version,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise credentials_error

    user = db.get(User, user_id)

    if user is None or not user.active or payload.get("tv", 0) != user.token_version:
        raise credentials_error

    if user.company is not None and not user.company.active:
        raise credentials_error
    expires_at = user.company.plan_expires_at if user.company is not None else None
    if (
        expires_at is not None
        and expires_at < datetime.now(timezone.utc)
        and request.method not in SAFE_METHODS
        and not request.url.path.startswith("/api/auth/")
    ):
        # An expired subscription makes the account read-only (data stays visible and exportable).
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Your subscription has expired. The account is read-only until it is renewed.",
        )
    db.info["actor"] = {"user_id": user.id, "company_id": user.company_id}
    return user
