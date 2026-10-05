import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services.email import send_email


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, user: User, purpose: str, lifetime: timedelta) -> str:
    """Create a single-use token (only its hash is stored) and invalidate older unused ones."""
    now = datetime.now(timezone.utc)
    for old in db.scalars(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
    ).all():
        old.used_at = now
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(user_id=user.id, token_hash=_hash(token), purpose=purpose, expires_at=now + lifetime))
    db.flush()
    return token


def consume_token(db: Session, token: str) -> User | None:
    """Return the user for a valid, unused, unexpired token and mark it used; otherwise None."""
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash(token)))
    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None or row.expires_at < now:
        return None
    user = db.get(User, row.user_id)
    if user is None or (not user.active and row.purpose != "invite"):
        return None
    row.used_at = now
    return user


def send_reset_email(user: User, token: str) -> bool:
    link = f"{settings.app_base_url.rstrip('/')}/?reset_token={token}"
    return send_email(
        user.email,
        "Reset your HoReCa Platform password",
        f"Hello {user.first_name},\n\nUse this link to choose a new password (valid for "
        f"{settings.password_reset_minutes} minutes, single use):\n{link}\n\n"
        "If you did not ask for this, ignore this message: your password is unchanged.\n",
    )


def send_invite_email(user: User, token: str, invited_by: User) -> bool:
    link = f"{settings.app_base_url.rstrip('/')}/?reset_token={token}"
    return send_email(
        user.email,
        "You were invited to HoReCa Platform",
        f"Hello {user.first_name},\n\n{invited_by.first_name} {invited_by.last_name} invited you as "
        f"{user.role}. Choose your password here (valid for {settings.invite_hours} hours):\n{link}\n",
    )
