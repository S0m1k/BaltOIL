"""Temporary file storage and download endpoint for generated XLSX reports."""
import asyncio
import hmac
import re
import time
import uuid as _uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from app.core.dependencies import CurrentUser

router = APIRouter(prefix="/reports/download", tags=["reports"])

# In-process store: file_id → (owner_user_id, filename, bytes, expires_at).
# Files are ephemeral — lost on service restart, which is fine for one-time downloads.
# TTL: 1 hour. Background task purges expired entries every 10 minutes.
_store: dict[str, tuple[str, str, bytes, float]] = {}
_TTL_SECONDS = 3600  # 1 hour
_MAX_STORE_BYTES = 200 * 1024 * 1024  # 200 MB guard

_SAFE_FILENAME = re.compile(r"[^\w.\-]")


def store_file(filename: str, content: bytes, owner_id: str) -> str:
    """Save content bound to owner and return a download token (str UUID).

    Rejects files that would push total in-memory size over _MAX_STORE_BYTES.
    """
    current_total = sum(len(v[2]) for v in _store.values())
    if current_total + len(content) > _MAX_STORE_BYTES:
        raise RuntimeError(
            "Хранилище временных файлов переполнено. Повторите попытку позже."
        )
    file_id = str(_uuid.uuid4())
    safe_name = _SAFE_FILENAME.sub("_", filename)
    _store[file_id] = (owner_id, safe_name, content, time.monotonic() + _TTL_SECONDS)
    return file_id


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [fid for fid, entry in _store.items() if entry[3] < now]
    for fid in expired:
        _store.pop(fid, None)


async def _purge_loop() -> None:
    """Background task: purge expired files every 10 minutes."""
    while True:
        await asyncio.sleep(600)
        _purge_expired()


@router.get("/{file_id}")
async def download_file(
    file_id: str,
    current_user: CurrentUser,
):
    """Download a previously generated report file (one-time, owner-only)."""
    _purge_expired()  # eager cleanup on every download request

    entry = _store.get(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Файл не найден или устарел")

    owner_id, filename, content, expires_at = entry

    if time.monotonic() > expires_at:
        _store.pop(file_id, None)
        raise HTTPException(status_code=404, detail="Файл не найден или устарел")

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
