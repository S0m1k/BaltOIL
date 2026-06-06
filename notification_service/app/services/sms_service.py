"""SMSC.ru SMS adapter.

Dumb sender: receives {phone, text} and pushes to SMSC HTTP API.
OTP generation/storage lives in auth_service, not here.
"""
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_SMSC_SEND_URL = "https://smsc.ru/sys/send.php"
_TIMEOUT = 10.0


async def send_sms(phone: str, text: str) -> bool:
    """Send an SMS via SMSC.ru. Returns True on success, False on any failure.

    Never raises — all errors are logged and swallowed so callers are not
    interrupted by SMS unavailability (mirror of email_enabled gating).
    """
    if not phone or not text:
        log.warning("sms_service.send_sms: phone or text is empty — skipped")
        return False

    if not settings.sms_enabled:
        log.info("sms_service.send_sms: SMS_ENABLED=false — skipped (phone=%s)", phone)
        return False

    params: dict = {
        "login":   settings.smsc_login,
        "psw":     settings.smsc_password,
        "phones":  phone,
        "mes":     text,
        "fmt":     3,          # JSON response
        "charset": "utf-8",
    }
    if settings.smsc_sender:
        params["sender"] = settings.smsc_sender

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_SMSC_SEND_URL, data=params)

        if resp.status_code != 200:
            log.error(
                "sms_service.send_sms: SMSC returned HTTP %s for phone=%s",
                resp.status_code, phone,
            )
            return False

        data = resp.json()
        if "error" in data:
            log.error(
                "sms_service.send_sms: SMSC error %s (code=%s) for phone=%s",
                data.get("error"), data.get("error_code"), phone,
            )
            return False

        log.info(
            "sms_service.send_sms: sent to phone=%s smsc_id=%s cnt=%s",
            phone, data.get("id"), data.get("cnt"),
        )
        return True

    except Exception:
        log.exception("sms_service.send_sms: unexpected error for phone=%s", phone)
        return False
