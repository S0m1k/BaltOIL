"""
Thin wrapper around aiosmtplib for fire-and-forget email delivery.

Design:
- Never raises — all errors are caught and logged.
- Returns True only when the message was accepted by the SMTP server.
- Gracefully degrades when SMTP is not configured (email_enabled=False or
  smtp_host missing) — logs a warning and returns False immediately.
"""
import logging
import socket
from contextlib import contextmanager
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from app.config import settings
from app.services.email_http import send_unisender_go

logger = logging.getLogger(__name__)


def _use_http_provider() -> bool:
    """True, когда письма надо слать через HTTP-API (порт 443), а не SMTP."""
    return settings.email_http_provider == "unisender_go" and bool(settings.unisender_go_api_key)


@contextmanager
def _prefer_ipv6():
    """Временно подменяет socket.getaddrinfo на IPv6-only.

    Нужно, когда провайдер VPS режет egress IPv4 на SMTP-порты (классика для
    RU-хостингов), а целевой SMTP доступен только по IPv6. asyncio через
    aiosmtplib не даёт явно выбрать AF_INET6 при коннекте, поэтому
    проще всего ограничить ответ резолвера.

    Эффект — на весь процесс, но контекст узкий (только время send_email).
    Внутренние Docker-хосты (auth_service и т.п.) при enable_ipv6=true в
    compose-сети получают AAAA, так что параллельные хождения не сломаются.
    """
    orig = socket.getaddrinfo

    def ipv6_only(host, port, family=0, *args, **kwargs):
        return orig(host, port, socket.AF_INET6, *args, **kwargs)

    socket.getaddrinfo = ipv6_only
    try:
        yield
    finally:
        socket.getaddrinfo = orig


async def send_email(to: str, subject: str, body_text: str) -> bool:
    """Send a plain-text email.

    Returns True if the SMTP server accepted the message, False otherwise.
    Never raises.
    """
    if not settings.email_enabled:
        logger.debug("email disabled (EMAIL_ENABLED=false), skipping send to %s", to)
        return False

    if _use_http_provider():
        return await send_unisender_go(to, subject, body_text)

    if not settings.smtp_host:
        logger.warning("email_enabled=true but SMTP_HOST is not set — cannot send email")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["X-BaltOIL-Notification"] = "1"
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # Взаимоисключимо: только один из use_tls / use_starttls. STARTTLS приоритетнее
    # — обычно правильный режим для порта 587 (subm). use_tls — для 465 (submissions).
    use_tls = settings.smtp_use_tls and not settings.smtp_use_starttls
    start_tls = settings.smtp_use_starttls

    send_kwargs = dict(
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=use_tls,
        start_tls=start_tls,
        timeout=10,
    )

    try:
        if settings.smtp_force_ipv6:
            with _prefer_ipv6():
                await aiosmtplib.send(msg, **send_kwargs)
        else:
            await aiosmtplib.send(msg, **send_kwargs)
        logger.info("email sent to=%s subject=%r", to, subject)
        return True
    except Exception:
        logger.exception("failed to send email to=%s subject=%r", to, subject)
        return False


async def send_email_with_attachment(
    to: str,
    subject: str,
    body_text: str,
    filename: str,
    content_bytes: bytes,
    mime_type: str,
) -> bool:
    """Send a plain-text email with a single file attachment.

    Returns True if the SMTP server accepted the message, False otherwise.
    Never raises.
    """
    if not settings.email_enabled:
        logger.debug("email disabled (EMAIL_ENABLED=false), skipping send to %s", to)
        return False

    if _use_http_provider():
        return await send_unisender_go(
            to, subject, body_text,
            filename=filename, content_bytes=content_bytes, mime_type=mime_type,
        )

    if not settings.smtp_host:
        logger.warning("email_enabled=true but SMTP_HOST is not set — cannot send email")
        return False

    logger.info(
        "sending email with attachment to=%s subject=%r filename=%r size=%d",
        to, subject, filename, len(content_bytes),
    )

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["X-BaltOIL-Notification"] = "1"
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    part = MIMEApplication(content_bytes, _subtype=mime_type.split("/")[-1])
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)

    # Взаимоисключимо: только один из use_tls / use_starttls. STARTTLS приоритетнее
    # — обычно правильный режим для порта 587 (subm). use_tls — для 465 (submissions).
    use_tls = settings.smtp_use_tls and not settings.smtp_use_starttls
    start_tls = settings.smtp_use_starttls

    send_kwargs = dict(
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=use_tls,
        start_tls=start_tls,
        timeout=10,
    )

    try:
        if settings.smtp_force_ipv6:
            with _prefer_ipv6():
                await aiosmtplib.send(msg, **send_kwargs)
        else:
            await aiosmtplib.send(msg, **send_kwargs)
        logger.info("email with attachment sent to=%s subject=%r", to, subject)
        return True
    except Exception:
        logger.exception("failed to send email with attachment to=%s subject=%r", to, subject)
        return False
