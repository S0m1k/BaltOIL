"""Unisender Go transactional email over HTTP (port 443).

Используется, когда VPS блокирует исходящий SMTP целиком (классика RU-хостинга):
SMTP-порты 25/465/587 закрыты, а 443 — открыт. Транспорт включается, когда
EMAIL_HTTP_PROVIDER=unisender_go и задан UNISENDER_GO_API_KEY.

Никогда не бросает исключения — всё логируется, наружу отдаётся bool
(зеркало поведения email_service на SMTP).
"""
import base64
import logging
from html import escape

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_URL = "https://goapi.unisender.ru/ru/transactional/api/v1/email/send.json"
_TIMEOUT = 15.0


def _html_from_text(text: str) -> str:
    """Минимальный HTML из plaintext — некоторые провайдеры требуют html-часть."""
    return "<pre style=\"font-family:inherit;white-space:pre-wrap;margin:0\">" + escape(text) + "</pre>"


async def send_unisender_go(
    to: str,
    subject: str,
    body_text: str,
    *,
    filename: str | None = None,
    content_bytes: bytes | None = None,
    mime_type: str | None = None,
) -> bool:
    """Отправить письмо (опц. с вложением) через Unisender Go. Возвращает True при успехе."""
    message: dict = {
        "recipients": [{"email": to}],
        "subject": subject,
        "from_email": settings.smtp_from,
        "from_name": settings.email_from_name,
        "body": {"plaintext": body_text, "html": _html_from_text(body_text)},
    }
    if filename and content_bytes:
        message["attachments"] = [{
            "type": mime_type or "application/octet-stream",
            "name": filename.replace("/", "_"),  # слэши в именах запрещены
            "content": base64.b64encode(content_bytes).decode("ascii"),
        }]

    headers = {
        "X-API-KEY": settings.unisender_go_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_URL, json={"message": message}, headers=headers)
        try:
            data = resp.json()
        except Exception:
            data = {}

        if resp.status_code == 200 and data.get("status") == "success":
            failed = data.get("failed_emails") or {}
            if failed:
                log.error("unisender_go: accepted but failed_emails=%s subject=%r", failed, subject)
                return False
            log.info("unisender_go: sent to=%s subject=%r job_id=%s", to, subject, data.get("job_id"))
            return True

        log.error(
            "unisender_go: send failed http=%s status=%s code=%s msg=%s subject=%r",
            resp.status_code, data.get("status"), data.get("code"), data.get("message"), subject,
        )
        return False
    except Exception:
        log.exception("unisender_go: unexpected error to=%s subject=%r", to, subject)
        return False
