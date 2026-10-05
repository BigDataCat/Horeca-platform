from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.user import User
from app.services.alerts import compute_alerts
from app.services.email import send_email

DIGEST_INTERVAL = timedelta(hours=24)


def send_alert_digests(db: Session, now: datetime | None = None) -> int:
    """E-mail owners a summary of critical/warning alerts, at most once per 24 h per company.

    Companies with nothing to report are skipped and not marked, so a new problem is reported
    on the next run. Returns the number of companies notified."""
    now = now or datetime.now(timezone.utc)
    notified = 0
    companies = db.scalars(
        select(Company).where(Company.active.is_(True), Company.alert_digest_enabled.is_(True))
    ).all()
    for company in companies:
        if company.last_alert_digest_at and now - company.last_alert_digest_at < DIGEST_INTERVAL:
            continue
        alerts = [a for a in compute_alerts(db, company.id) if a["severity"] in {"critical", "warning"}]
        if not alerts:
            continue
        owners = db.scalars(
            select(User).where(User.company_id == company.id, User.role == "owner", User.active.is_(True))
        ).all()
        lines = "\n".join(f"- [{a['severity']}] {a['message']}" for a in alerts[:50])
        body = f"{len(alerts)} item(s) need attention in {company.name}:\n\n{lines}\n\nOpen the Alerts tab for details."
        sent = [send_email(owner.email, f"HoReCa alerts for {company.name}", body) for owner in owners]
        if any(sent):
            company.last_alert_digest_at = now
            notified += 1
    db.commit()
    return notified
