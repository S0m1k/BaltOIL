"""Thin HTTP client that delegates SMS delivery to notification_service.

auth_service calls this after generating and storing an OTP code.
notification_service does the actual SMSC.ru call — auth_service never
talks to SMSC directly.
"""
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_TIMEOUT = 5.0

_MESSAGES = {
    "login": "Код для входа в СЗТК: {code}. Никому не сообщайте код.",
    "reset": "Код для сброса пароля СЗТК: {code}. Никому не сообщайте код.",
}


async def send_otp(phone: str, code: str, purpose: str) -> bool:
    """Send an OTP code via notification_service /internal/sms/send.

    Returns True if notification_service accepted the request and reported
    sent=true. Always returns False on any error — never raises.
    """
    settings = get_settings()
    template = _MESSAGES.get(purpose, "Ваш код: {code}. Никому не сообщайте код.")
    text = template.format(code=code)

    url = f"{settings.notification_service_url}/internal/sms/send"
    headers = {
        "X-Internal-Secret": settings.internal_api_secret,
        "Content-Type": "application/json",
    }
    payload = {"phone": phone, "text": text}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            log.error(
                "sms_client.send_otp: notification_service returned HTTP %s "
                "for phone=%s purpose=%s",
                resp.status_code, phone, purpose,
            )
            return False

        data = resp.json()
        sent = bool(data.get("sent", False))
        if not sent:
            log.warning(
                "sms_client.send_otp: notification_service reported sent=false "
                "for phone=%s purpose=%s",
                phone, purpose,
            )
        return sent

    except Exception:
        log.exception(
            "sms_client.send_otp: unexpected error for phone=%s purpose=%s",
            phone, purpose,
        )
        return False
