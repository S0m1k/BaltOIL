"""Internal endpoints for service-to-service communication.

These routes are NOT exposed through nginx — they are only accessible
on the Docker internal network. Auth is done via X-Internal-Secret header
(HMAC-safe comparison, same secret used by all services).
"""
import base64
import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.config import settings
from app.services.email_service import send_email_with_attachment
from app.services import sms_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

# 25 MB raw → base64 is ~33.3 MB; cap at 34 MB of base64 text
_MAX_BASE64_LEN = 34 * 1024 * 1024


def _require_internal(
    x_internal_secret: Annotated[str, Header(alias="X-Internal-Secret")],
) -> None:
    if not hmac.compare_digest(x_internal_secret, settings.internal_api_secret):
        raise HTTPException(status_code=403, detail="Invalid internal secret")


class AttachmentPayload(BaseModel):
    filename: str
    content_base64: str
    mime_type: str

    @field_validator("content_base64")
    @classmethod
    def check_size(cls, v: str) -> str:
        if len(v) > _MAX_BASE64_LEN:
            raise ValueError("attachment too large (max 25 MB)")
        return v


class SendWithAttachmentRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    attachment: AttachmentPayload


class SendWithAttachmentResponse(BaseModel):
    sent: bool


@router.post(
    "/email/send-with-attachment",
    response_model=SendWithAttachmentResponse,
    dependencies=[Depends(_require_internal)],
)
async def send_email_with_attachment_endpoint(
    req: SendWithAttachmentRequest,
) -> SendWithAttachmentResponse:
    """Send an email with a single file attachment.

    Decodes base64 content, delegates to email_service. Returns {sent: bool}.
    Does not raise on SMTP failure — caller inspects the sent flag.
    """
    try:
        content_bytes = base64.b64decode(req.attachment.content_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64")

    sent = await send_email_with_attachment(
        to=str(req.to),
        subject=req.subject,
        body_text=req.body,
        filename=req.attachment.filename,
        content_bytes=content_bytes,
        mime_type=req.attachment.mime_type,
    )
    return SendWithAttachmentResponse(sent=sent)


class SendSmsRequest(BaseModel):
    phone: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class SendSmsResponse(BaseModel):
    sent: bool


@router.post(
    "/sms/send",
    response_model=SendSmsResponse,
    dependencies=[Depends(_require_internal)],
)
async def send_sms_endpoint(req: SendSmsRequest) -> SendSmsResponse:
    """Send an SMS via SMSC.ru. Returns {sent: bool}.

    Does not raise on SMSC failure — caller inspects the sent flag.
    OTP generation/storage is the caller's responsibility (auth_service).
    """
    sent = await sms_service.send_sms(phone=req.phone, text=req.text)
    return SendSmsResponse(sent=sent)
