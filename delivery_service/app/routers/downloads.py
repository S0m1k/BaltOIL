"""Temporary file storage and download endpoint for generated XLSX reports."""
import hmac
import re
import uuid as _uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from app.core.dependencies import CurrentUser

router = APIRouter(prefix="/reports/download", tags=["reports"])

# In-process store: file_id → (owner_user_id, filename, bytes).
# Files are ephemeral — lost on service restart, which is fine for one-time downloads.
_store: dict[str, tuple[str, str, bytes]] = {}

_SAFE_FILENAME = re.compile(r"[^\w.\-]")


def store_file(filename: str, content: bytes, owner_id: str) -> str:
    """Save content bound to owner and return a download token (str UUID)."""
    file_id = str(_uuid.uuid4())
    # Sanitise filename: keep only word chars, dots, dashes
    safe_name = _SAFE_FILENAME.sub("_", filename)
    _store[file_id] = (owner_id, safe_name, content)
    return file_id


@router.get("/{file_id}")
async def download_file(
    file_id: str,
    current_user: CurrentUser,
):
    """Download a previously generated report file (one-time, owner-only)."""
    entry = _store.get(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Файл не найден или устарел")

    owner_id, filename, content = entry

    # Constant-time comparison to prevent timing oracle on file_id ownership
    if not hmac.compare_digest(owner_id, str(current_user.id)):
        # Return 404, not 403 — don't confirm the file exists for other users
        raise HTTPException(status_code=404, detail="Файл не найден или устарел")

    # Remove after download (one-time link)
    _store.pop(file_id, None)

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
