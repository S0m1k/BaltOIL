"""
Thin wrapper around aiosmtplib for fire-and-forget email delivery.

Design:
- Never raises — all errors are caught and logged.
- Returns True only when the message was accepted by the SMTP server.
- Gracefully degrades when SMTP is not configured (email_enabled=False or
  smtp_host missing) — logs a warning and returns False immediately.
"""
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body_text: str) -> bool:
    """Send a plain-text email.

    Returns True if the SMTP server accepted the message, False otherwise.
    Never raises.
    """
    if not settings.email_enabled:
        logger.debug("email disabled (EMAIL_ENABLED=false), skipping send to %s", to)
        return False

    if not settings.smtp_host:
        logger.warning("email_enabled=true but SMTP_HOST is not set — cannot send email")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["X-BaltOIL-Notification"] = "1"
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            timeout=10,
        )
        logger.info("email sent to=%s subject=%r", to, subject)
        return True
    except Exception:
        logger.exception("failed to send email to=%s subject=%r", to, subject)
        return False
