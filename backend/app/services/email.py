"""Outgoing e-mail. Backends: ``smtp`` (real), ``console`` (log only, development), ``memory`` (tests)."""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("horeca.email")
outbox: list[dict] = []  # only filled by the memory backend


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text e-mail. Never raises: returns False (and logs) if delivery failed."""
    backend = settings.email_backend
    if backend == "memory":
        outbox.append({"to": to, "subject": subject, "body": body})
        return True
    if backend == "console":
        # Development only: the body can contain one-time links.
        logger.info('{"event": "email_console", "to": "%s", "subject": "%s"}\n%s', to, subject, body)
        return True
    if not settings.smtp_host:
        logger.warning('{"event": "email_not_sent_smtp_not_configured", "to": "%s"}', to)
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(message)
        return True
    except Exception:
        logger.exception('{"event": "email_send_failed", "to": "%s"}', to)
        return False
